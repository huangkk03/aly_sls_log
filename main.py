# coding=utf-8
import os
import time
import glob
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from aliyun.log import LogClient, GetLogsRequest

# ------------------ 配置信息 ------------------
ACCESS_KEY_ID = os.getenv("SLS_AK_ID", "ALIBABA_CLOUD_ACCESS_KEY_ID")
ACCESS_KEY_SECRET = os.getenv("SLS_AK_SECRET", "ALIBABA_CLOUD_ACCESS_KEY_SECRET")
ENDPOINT = "cn-shenzhen-finance-1.log.aliyuncs.com"
PROJECT = "k8s-log-cb83a41a9c39e43d591695cd81960951f"
API_TOKEN = "ALIBABA_CLOUD_API_TOKEN"

client = LogClient(ENDPOINT, ACCESS_KEY_ID, ACCESS_KEY_SECRET)
app = FastAPI()

LOG_DIR = os.path.join(os.getcwd(), "downloaded_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ------------------ 工具函数 ------------------

class LogRequest(BaseModel):
    logstore: str
    start_time: str
    end_time: str

def parse_time(t: str) -> int:
    t = t.strip().strip('"').strip("'").replace('T', ' ')
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(t.split('.')[0], fmt) # 忽略毫秒部分
            return int(dt.timestamp())
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"时间解析错误: {t}")

async def delayed_delete(file_path: str, delay: int = 180):
    """在指定秒数后删除文件"""
    await asyncio.sleep(delay)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"已自动清理临时文件: {file_path}")
    except Exception as e:
        print(f"清理文件失败: {e}")

# ------------------ 核心同步拉取逻辑 ------------------

def fetch_logs_sync(logstore: str, start_ts: int, end_ts: int, filename: str):
    """同步拉取所有日志直到完成"""
    file_path = os.path.join(LOG_DIR, filename)
    line_limit = 100
    current_offset = 0
    total_count = 0

    with open(file_path, "w", encoding="utf-8") as f:
        while True:
            req = GetLogsRequest(PROJECT, logstore, start_ts, end_ts, line=line_limit, offset=current_offset)
            res = client.get_logs(req)
            logs = res.get_logs()

            if not logs:
                break

            for log in logs:
                log_text = getattr(log, 'contents', {}).get('content', '')
                if log_text:
                    f.write(f"{log_text}\n")
                    total_count += 1

            if len(logs) < line_limit:
                break
            
            current_offset += line_limit
            # 如果日志量极大，建议在此处加微小 sleep 避免触发 SLS 限流
    
    return total_count

# ------------------ 路由接口 ------------------

@app.post("/fetch_logs")
async def fetch_logs(req: LogRequest, background_tasks: BackgroundTasks, authorization: str = Header(None)):
    # 鉴权
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    start_ts = parse_time(req.start_time)
    end_ts = parse_time(req.end_time)

    # 1. 生成唯一文件名
    file_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{req.logstore}_{file_id}.txt"
    file_path = os.path.join(LOG_DIR, filename)

    # 2. 同步执行拉取（API 会在这里阻塞直到文件写完）
    try:
        # 使用 run_in_executor 避免阻塞 FastAPI 的主事件循环
        loop = asyncio.get_event_loop()
        count = await loop.run_in_executor(None, fetch_logs_sync, req.logstore, start_ts, end_ts, filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"日志获取失败: {str(e)}")

    if count == 0:
        return {"text": "在指定时间内未发现相关日志内容。"}

    # 3. 注册“3分钟后自动删除”的后台任务
    background_tasks.add_task(delayed_delete, file_path, 180)

    # 4. 返回链接
    download_url = f"http://10.254.20.33:8000/download/{filename}"
    return {
        "text": f"### 日志提取完成 (共 {count} 条)\n\n[点击点击查看/下载日志]({download_url})\n\n**安全提示：该链接将在 3 分钟后失效并自动物理删除。**"
    }

@app.get("/download/{filename}")
async def download_file(filename: str):
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(LOG_DIR, safe_filename)

    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=safe_filename, media_type='text/plain')
    
    raise HTTPException(status_code=404, detail="文件已过期或不存在")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
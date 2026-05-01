import argparse
import logging
from app import create_app
from app.scheduler.job_scheduler import job_scheduler
from app.models.database import db_manager


def parse_args():
    parser = argparse.ArgumentParser(description='股票量化助手后端服务')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000, help='监听端口 (默认: 5000)')
    parser.add_argument('--debug', action='store_true', help='开启调试模式')
    return parser.parse_args()


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = create_app()


@app.before_request
def ensure_scheduler():
    if not job_scheduler.scheduler.running:
        job_scheduler.start()


@app.teardown_appcontext
def shutdown_scheduler(exception=None):
    pass


def main():
    args = parse_args()
    try:
        logger.info(f"启动股票量化助手服务... {args.host}:{args.port} debug={args.debug}")
        job_scheduler.start()
        app.run(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        logger.info("正在关闭服务...")
    finally:
        job_scheduler.shutdown()
        db_manager.close_all()
        logger.info("服务已关闭")


if __name__ == '__main__':
    main()

from flask import Blueprint, request, jsonify
import pandas as pd
from app.services.workflow_service import workflow_service
from app.scheduler.job_scheduler import job_scheduler
from app.models.database import db_manager
from app.services.analysis_service import analyze_stock

api_bp = Blueprint('api', __name__)


@api_bp.route('/stock/register', methods=['POST'])
def register_stock():
    data = request.get_json()
    if not data or 'stock' not in data:
        return jsonify({'success': False, 'message': '缺少 stock 参数'}), 400

    stock = data['stock'].strip()
    if not stock:
        return jsonify({'success': False, 'message': 'stock 参数不能为空'}), 400

    try:
        result = workflow_service.register_stock(stock)

        if result['success'] and '已创建' in result['message']:
            for wf_id in result['workflows']:
                wf_data = workflow_service.workflows.get(wf_id)
                if wf_data:
                    job_scheduler.add_workflow_job(wf_id, wf_data)

        return jsonify(result)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@api_bp.route('/stock/code', methods=['POST'])
def upsert_stock_code():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'success': False, 'message': '缺少 name 参数'}), 400

    name = data['name'].strip()
    if not name:
        return jsonify({'success': False, 'message': 'name 不能为空'}), 400

    if not any(k in data for k in ('a', 'hk', 'us')):
        return jsonify({'success': False, 'message': '至少需要提供 a、hk、us 中的一个市场代码'}), 400

    try:
        db_manager.upsert_stock_code(
            name=name,
            a_code=data.get('a'),
            hk_code=data.get('hk'),
            us_code=data.get('us'),
        )
        return jsonify({'success': True, 'message': f'股票映射 "{name}" 已保存'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@api_bp.route('/stock/codes', methods=['GET'])
def get_stock_codes():
    try:
        df = db_manager.get_all_stock_codes()
        rows = []
        for _, row in df.iterrows():
            rows.append({
                'name': row['name'],
                'a_code': row.get('a_code') if not pd.isna(row.get('a_code')) else None,
                'hk_code': row.get('hk_code') if not pd.isna(row.get('hk_code')) else None,
                'us_code': row.get('us_code') if not pd.isna(row.get('us_code')) else None,
            })
        return jsonify({'success': True, 'count': len(rows), 'codes': rows})
    except Exception as e:
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@api_bp.route('/stock/decision', methods=['POST'])
def stock_decision():
    data = request.get_json()
    if not data or 'stock' not in data:
        return jsonify({'success': False, 'message': '缺少 stock 参数'}), 400

    stock = data['stock'].strip()
    if not stock:
        return jsonify({'success': False, 'message': 'stock 参数不能为空'}), 400

    interval = data.get('interval', 'daily')
    if interval not in ('daily', '120min', '90min', '60min'):
        return jsonify({'success': False, 'message': 'interval 必须是 daily/120min/90min/60min'}), 400

    try:
        result = analyze_stock(stock, interval=interval)
        return jsonify(result)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@api_bp.route('/stock/<stock_code>/workflows', methods=['GET'])
def get_stock_workflows(stock_code):
    workflows = workflow_service.get_stock_workflows(stock_code)
    return jsonify({
        'success': True,
        'stock_code': stock_code,
        'workflows': workflows
    })


@api_bp.route('/workflows', methods=['GET'])
def get_all_workflows():
    workflows = workflow_service.get_all_workflows()
    return jsonify({
        'success': True,
        'count': len(workflows),
        'workflows': workflows
    })


@api_bp.route('/workflows/<workflow_id>', methods=['DELETE'])
def delete_workflow(workflow_id):
    job_scheduler.remove_workflow_job(workflow_id)
    deleted = workflow_service.delete_workflow(workflow_id)

    if deleted:
        return jsonify({'success': True, 'message': f'工作流 {workflow_id} 已删除'})
    else:
        return jsonify({'success': False, 'message': f'工作流 {workflow_id} 不存在'}), 404


@api_bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'scheduler_running': job_scheduler.scheduler.running})

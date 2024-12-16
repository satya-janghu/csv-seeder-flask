from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
from app import db
from app.models import Task
from app.tasks import process_csv
from datetime import datetime
import os
from config import Config

bp = Blueprint('main', __name__)

@bp.route('/api/tasks', methods=['POST'])
def create_task():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    task_name = request.form.get('name', 'Untitled Task')
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file:
        # Save input file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        input_path = os.path.join(Config.UPLOAD_FOLDER, f'{timestamp}_{filename}')
        output_path = os.path.join(Config.DOWNLOAD_FOLDER, f'{task_name}_{timestamp}.csv')
        
        file.save(input_path)
        
        # Create task record
        task = Task(
            name=task_name,
            status='PENDING',
            input_file=input_path,
            output_file=output_path
        )
        db.session.add(task)
        db.session.commit()
        
        # Start processing
        process_csv.delay(task.id)
        
        return jsonify(task.to_dict()), 201

@bp.route('/api/tasks', methods=['GET'])
def get_tasks():
    tasks = Task.query.order_by(Task.created_at.desc()).all()
    return jsonify([task.to_dict() for task in tasks])

@bp.route('/api/tasks/<int:task_id>', methods=['GET'])
def get_task(task_id):
    task = Task.query.get_or_404(task_id)
    return jsonify(task.to_dict())

@bp.route('/api/tasks/<int:task_id>/download', methods=['GET'])
def download_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if task.status != 'COMPLETED':
        return jsonify({'error': 'Task not completed'}), 400
    
    if not os.path.exists(task.output_file):
        return jsonify({'error': 'Output file not found'}), 404
    
    return send_file(
        task.output_file,
        as_attachment=True,
        download_name=os.path.basename(task.output_file)
    ) 
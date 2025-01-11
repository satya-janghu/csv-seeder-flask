from datetime import datetime
from app import db

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='PENDING')  # PENDING, PROCESSING, COMPLETED, FAILED
    total_items = db.Column(db.Integer, default=0)
    processed_items = db.Column(db.Integer, default=0)
    input_file = db.Column(db.String(255))
    output_file = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'total_items': self.total_items,
            'processed_items': self.processed_items,
            'progress': (self.processed_items / self.total_items * 100) if self.total_items > 0 else 0,
            'input_file': self.input_file,
            'output_file': self.output_file,
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        } 

# Add this new model to store query results
class QueryResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(500), unique=True, index=True)
    competitors = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow) 
from flask import Blueprint

# blueprint 容器（實作將分檔加入）
health_bp = Blueprint('health', __name__)
auth_bp = Blueprint('auth', __name__)
report_bp = Blueprint('report', __name__)
recommender_bp = Blueprint('recommender', __name__)
admin_bp = Blueprint('admin', __name__)
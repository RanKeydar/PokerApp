from flask import Blueprint, render_template
from pokerapp.routes.main import login_required, get_current_user

bp_record = Blueprint("record", __name__)


@bp_record.route("/record")
@login_required
def record():
    user = get_current_user()
    return render_template("record.html", current_user=user)

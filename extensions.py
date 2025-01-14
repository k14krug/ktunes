from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR


db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()

# The shared APScheduler instance
scheduler = BackgroundScheduler()

job_status = {} # used for the scheduler dashboard

def configure_scheduler(app):
    """
    Configure the BackgroundScheduler with a SQLAlchemy job store,
    then start the scheduler.
    """
    # Using the same DB that Flask uses
    job_store = SQLAlchemyJobStore(url=app.config['SQLALCHEMY_DATABASE_URI'])
    scheduler.configure(jobstores={"default": job_store})
    scheduler.start()
    # Add a listener to capture scheduler job status. This will be displayed on the dashboard
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)


def job_listener(event):
    job_id = event.job_id
    if event.exception:
        # Job failed
        job_status[job_id] = {
            "status": "failed",
            "exception": str(event.exception),
            "run_time": event.scheduled_run_time  # when job was scheduled to run
        }
    else:
        # Job succeeded
        job_status[job_id] = {
            "status": "succeeded",
            "run_time": event.scheduled_run_time
        }



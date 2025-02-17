from flask import jsonify, render_template, request, redirect, url_for, flash
from . import scheduler_bp  
from extensions import scheduler, job_status
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()

@scheduler_bp.route('/jobs', methods=['GET'])
def list_jobs():
    """
    List all scheduled jobs.
    """
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })
    return jsonify({"jobs": jobs})


@scheduler_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    """f
    Get details of a specific job by ID.
    """
    job = scheduler.get_job(job_id)
    if not job:
        return jsonify({"error": f"Job with ID {job_id} not found"}), 404

    return jsonify({
        "id": job.id,
        "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        "trigger": str(job.trigger)
    })

#

@scheduler_bp.route('/jobs/<job_id>', methods=['DELETE', 'POST'])
@csrf.exempt
def delete_job(job_id):
    """
    Remove a specific job by ID.
    """
    job = scheduler.get_job(job_id)
    if not job:
        return jsonify({"error": f"Job with ID {job_id} not found"}), 404

    scheduler.remove_job(job_id)
    flash(f"Job {job_id} removed successfully", "success")
    return redirect(url_for('scheduler_bp.dashboard'))


@scheduler_bp.route('/jobs', methods=['POST'])
def add_job():
    """
    Example endpoint to add a job.
    Adjust the parameters to fit your requirements.
    """
    # Example of adding a job
    scheduler.add_job(
        id="test_job",
        func='tasks.scheduled_tasks:export_default_playlist_to_spotify_task',
        trigger="interval",
        minutes=10,
        replace_existing=True
    )
    return jsonify({"message": "Test job added successfully"})

@scheduler_bp.route('/dashboard', methods=['GET'])
def dashboard():
    jobs = scheduler.get_jobs()
    # Pass both jobs and their statuses to the template
    return render_template('dashboard.html', jobs=jobs, job_status=job_status)

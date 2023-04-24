"""
backup view
"""

import logging
import time

from flask import current_app, render_template, jsonify
from . import blueprint
from . import logs
import os
from borgweb.borg import BorgClient
import json
from pathlib import Path

log = logging.getLogger(__name__)


@blueprint.route('/cacheflush', methods=['GET'])
def invalidate_backup_cache():
    try:
        # Invalidate the cache by removing the file
        filepath = Path(current_app.config["STATUS_CACHE_PATH"])
        if filepath.is_file():
            os.remove(filepath)
        return "{'status':'ok'}"
    except Exception as e:
        error_str = f"Error processing cache invalidate request {e.__class__.__name__}: {e}"
        log.exception(error_str) if log.isEnabledFor(logging.DEBUG) else log.error(error_str)
        return {"error": error_str}


@blueprint.route('/backups', methods=['GET'])
def get_backups():
    try:
        # Get data from cache, and if invalid create it
        return load_backup_cache() or create_backup_status()
    except Exception as e:
        error_str = f"Error processing backups request {e.__class__.__name__}:{e}"
        log.exception(error_str) if log.isEnabledFor(logging.DEBUG) else log.error(error_str)
        return {"error": error_str}


def save_backup_cache(cache_data):
    with open(current_app.config["STATUS_CACHE_PATH"], "w") as f:
        f.write(cache_data)


def load_backup_cache():
    filepath = Path(current_app.config["STATUS_CACHE_PATH"])
    cache_ttl = current_app.config["STATUS_CACHE_TTL"]
    if filepath.is_file() and ((time.time() - filepath.stat().st_mtime) < cache_ttl):
        log.info(f"Loading backups cache from {filepath}")
        with open(filepath, "r") as f:
            return json.load(f)
    else:
        return None


def create_backup_status():
    repos = dict(current_app.config["BACKUP_REPOS"])
    output = { "repos": {}, "bargraph":[] }
    borg = BorgClient(current_app.config["BORG_PATH"])

    log.info(f"Creating backups status")
    for repo, repo_config in repos.items():
        repo_data = {}
        repo_graph = {"type": "bar", "name": repo, "x": [], "y": []}
        repo_data["backups"] = []
        repo_data["script"] = repo_config.get("script", "")

        # Get repo info
        borg.set_repo(repo_config["repo_path"], pwd=repo_config["repo_pwd"])
        borg_info = borg.info()
        repo_data.update(borg_info)

        # Get backup list
        borg_list = borg.list()
        repo_data["backups"].extend(borg_list)

        # Set the default status to not run
        repo_data["last_result"] = "warning"
        repo_data["last_date"] = ""
        repo_data["last_time"] = ""
        repo_data["archives"] = len(repo_data["backups"])

        # Get last info run for this repo
        # TODO Configure number of run status to get
        log_dir, log_files = logs._get_logs(repo)
        if(len(log_files) > 0):
            repo_data["last_log"] = log_files[0]
            repo_data["last_result"], repo_data["last_date"], repo_data["last_time"] = (
                logs.getLogFileStatus(log_dir + "/" + log_files[0])
            )

        # Get details on each backup
        for backup in repo_data["backups"]:
            borg_archinfo = borg.info(archive=backup["name"])
            if borg_archinfo:
                backup.update(borg_archinfo)
                if "date" in borg_archinfo and borg_archinfo.get("size"):
                    repo_graph["x"].append(borg_archinfo["date"])
                    repo_graph["y"].append(borg_archinfo["size"])
                else:
                    log.error(f"Backup {borg_archinfo} has no date/size")
            else:
                log.info(f"No information for repo {backup['name']}")
            # TODO: actually get the backup log file

        output["repos"][repo] = repo_data
        output["bargraph"].append(repo_graph)
        output["ctime"] = time.ctime()

    # Convert the data to json, cache it and return it
    status_data = json.dumps(output)
    save_backup_cache(status_data)
    log.info("Backups status created")
    return status_data

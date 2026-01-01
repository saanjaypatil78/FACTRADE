import os
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import schedule
import time
from threading import Thread
import structlog

logger = structlog.get_logger()


class DocumentChangeHandler(FileSystemEventHandler):
    def __init__(self, auto_updater):
        self.auto_updater = auto_updater
        self.pending_changes = set()
        self.last_process_time = time.time()

    def on_created(self, event):
        if not event.is_directory:
            logger.info("file_created", path=event.src_path)
            self.pending_changes.add(('created', event.src_path))
            self._maybe_process()

    def on_modified(self, event):
        if not event.is_directory:
            logger.info("file_modified", path=event.src_path)
            self.pending_changes.add(('modified', event.src_path))
            self._maybe_process()

    def on_deleted(self, event):
        if not event.is_directory:
            logger.info("file_deleted", path=event.src_path)
            self.pending_changes.add(('deleted', event.src_path))
            self._maybe_process()

    def _maybe_process(self):
        current_time = time.time()
        if current_time - self.last_process_time > 5:
            if self.pending_changes:
                self.auto_updater.process_changes(list(self.pending_changes))
                self.pending_changes.clear()
                self.last_process_time = current_time


class AutoUpdater:
    def __init__(self, config, rag_system=None):
        self.config = config
        self.update_config = config.auto_update
        self.rag_system = rag_system
        
        self.document_index = {}
        self.version_history = []
        self.observer = None
        self.scheduler_thread = None
        self.is_running = False
        
        self._load_document_index()
        logger.info("auto_updater_initialized")

    def start(self):
        if not self.update_config.enabled:
            logger.info("auto_updater_disabled")
            return

        logger.info("starting_auto_updater")
        self.is_running = True
        
        if self.update_config.monitoring.watch_directories:
            self._start_file_watcher()
        
        if self.update_config.strategy.update_schedule:
            self._start_scheduler()

    def stop(self):
        logger.info("stopping_auto_updater")
        self.is_running = False
        
        if self.observer:
            self.observer.stop()
            self.observer.join()
        
        self._save_document_index()

    def _start_file_watcher(self):
        logger.info("starting_file_watcher")
        
        self.observer = Observer()
        event_handler = DocumentChangeHandler(self)
        
        for directory in self.update_config.monitoring.watch_directories:
            dir_path = Path(directory)
            if dir_path.exists():
                self.observer.schedule(event_handler, str(dir_path), recursive=True)
                logger.info("watching_directory", path=str(dir_path))
            else:
                logger.warning("watch_directory_not_found", path=str(dir_path))
        
        self.observer.start()

    def _start_scheduler(self):
        logger.info("starting_scheduler", schedule=self.update_config.strategy.update_schedule)
        
        schedule.every().day.at("02:00").do(self._scheduled_update)
        
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        
        self.scheduler_thread = Thread(target=run_scheduler, daemon=True)
        self.scheduler_thread.start()

    def _scheduled_update(self):
        logger.info("running_scheduled_update")
        self.full_reindex()

    def process_changes(self, changes: List[tuple]):
        logger.info("processing_changes", count=len(changes))
        
        files_to_add = []
        files_to_update = []
        files_to_delete = []
        
        for change_type, file_path in changes:
            if not self._is_supported_file(file_path):
                continue
            
            if change_type == 'created':
                files_to_add.append(file_path)
            elif change_type == 'modified':
                files_to_update.append(file_path)
            elif change_type == 'deleted':
                files_to_delete.append(file_path)
        
        if self.rag_system:
            if files_to_delete:
                self._delete_documents(files_to_delete)
            
            if files_to_add or files_to_update:
                self._update_documents(files_to_add + files_to_update)
        
        self._create_version_snapshot()

    def _is_supported_file(self, file_path: str) -> bool:
        supported_extensions = [f".{fmt}" for fmt in self.config.document_processing.supported_formats]
        return any(file_path.endswith(ext) for ext in supported_extensions)

    def _update_documents(self, file_paths: List[str]):
        logger.info("updating_documents", count=len(file_paths))
        
        for file_path in file_paths:
            try:
                file_hash = self._calculate_file_hash(file_path)
                
                if file_path in self.document_index:
                    if self.document_index[file_path]['hash'] == file_hash:
                        logger.debug("file_unchanged", path=file_path)
                        continue
                
                if self.rag_system:
                    self.rag_system.add_documents([file_path])
                
                self.document_index[file_path] = {
                    'hash': file_hash,
                    'last_updated': datetime.utcnow().isoformat(),
                    'size': os.path.getsize(file_path)
                }
                
                logger.info("document_updated", path=file_path)
            
            except Exception as e:
                logger.error("failed_to_update_document", path=file_path, error=str(e))

    def _delete_documents(self, file_paths: List[str]):
        logger.info("deleting_documents", count=len(file_paths))
        
        for file_path in file_paths:
            try:
                if self.rag_system:
                    self.rag_system.delete_document_by_source(file_path)
                
                if file_path in self.document_index:
                    del self.document_index[file_path]
                
                logger.info("document_deleted", path=file_path)
            
            except Exception as e:
                logger.error("failed_to_delete_document", path=file_path, error=str(e))

    def _calculate_file_hash(self, file_path: str) -> str:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def full_reindex(self):
        logger.info("starting_full_reindex")
        
        all_files = []
        for directory in self.update_config.monitoring.watch_directories:
            dir_path = Path(directory)
            if dir_path.exists():
                for ext in self.config.document_processing.supported_formats:
                    all_files.extend(dir_path.rglob(f"*.{ext}"))
        
        files_to_process = []
        for file_path in all_files:
            file_str = str(file_path)
            
            if os.path.getsize(file_str) > self.config.document_processing.max_file_size_mb * 1024 * 1024:
                logger.warning("file_too_large", path=file_str)
                continue
            
            file_hash = self._calculate_file_hash(file_str)
            
            if file_str not in self.document_index or self.document_index[file_str]['hash'] != file_hash:
                files_to_process.append(file_str)
        
        if files_to_process:
            if self.update_config.strategy.batch_updates:
                batch_size = self.update_config.strategy.batch_size
                for i in range(0, len(files_to_process), batch_size):
                    batch = files_to_process[i:i+batch_size]
                    self._update_documents(batch)
            else:
                self._update_documents(files_to_process)
        
        orphaned_files = set(self.document_index.keys()) - set(str(f) for f in all_files)
        if orphaned_files:
            self._delete_documents(list(orphaned_files))
        
        self._create_version_snapshot()
        logger.info("full_reindex_completed", files_processed=len(files_to_process))

    def _create_version_snapshot(self):
        if not self.update_config.versioning.enabled:
            return
        
        version_data = {
            "version_id": datetime.utcnow().isoformat(),
            "document_count": len(self.document_index),
            "documents": self.document_index.copy()
        }
        
        self.version_history.append(version_data)
        
        max_versions = self.update_config.versioning.max_versions
        if len(self.version_history) > max_versions:
            self.version_history = self.version_history[-max_versions:]
        
        version_dir = Path(self.update_config.versioning.version_directory)
        version_dir.mkdir(parents=True, exist_ok=True)
        
        version_file = version_dir / f"version_{version_data['version_id'].replace(':', '-')}.json"
        with open(version_file, 'w') as f:
            json.dump(version_data, f, indent=2)
        
        old_versions = sorted(version_dir.glob("version_*.json"))[:-max_versions]
        for old_version in old_versions:
            old_version.unlink()
        
        logger.info("version_snapshot_created", version_id=version_data['version_id'])

    def _load_document_index(self):
        index_file = Path(self.config.vector_store.persist_directory) / "document_index.json"
        
        if index_file.exists():
            try:
                with open(index_file, 'r') as f:
                    self.document_index = json.load(f)
                logger.info("document_index_loaded", documents=len(self.document_index))
            except Exception as e:
                logger.error("failed_to_load_document_index", error=str(e))
                self.document_index = {}
        else:
            self.document_index = {}

    def _save_document_index(self):
        index_file = Path(self.config.vector_store.persist_directory) / "document_index.json"
        
        try:
            index_file.parent.mkdir(parents=True, exist_ok=True)
            with open(index_file, 'w') as f:
                json.dump(self.document_index, f, indent=2)
            logger.info("document_index_saved", documents=len(self.document_index))
        except Exception as e:
            logger.error("failed_to_save_document_index", error=str(e))

    def get_version_history(self) -> List[Dict[str, Any]]:
        return self.version_history

    def rollback_to_version(self, version_id: str):
        logger.info("rolling_back_to_version", version_id=version_id)
        
        version = next((v for v in self.version_history if v['version_id'] == version_id), None)
        
        if not version:
            version_file = Path(self.update_config.versioning.version_directory) / f"version_{version_id.replace(':', '-')}.json"
            if version_file.exists():
                with open(version_file, 'r') as f:
                    version = json.load(f)
        
        if not version:
            raise ValueError(f"Version {version_id} not found")
        
        self.document_index = version['documents']
        
        if self.rag_system:
            self.rag_system.clear()
            files_to_load = list(self.document_index.keys())
            self.rag_system.add_documents(files_to_load)
        
        logger.info("rollback_completed", version_id=version_id)

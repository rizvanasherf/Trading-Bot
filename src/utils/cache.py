"""
src/utils/cache.py
------------------
Two-Level Cache: L1 in-memory dictionary, and L2 disk cache using Parquet
files (for DataFrames) and JSON files (for dicts/lists), with sidecar metadata.
"""
import os
import hashlib
import json
import time
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Union
import pandas as pd
from utils.logger import logger

class MarketDataCache:
    TTL_INSTRUMENTS = 86400
    TTL_HISTORICAL = 900
    TTL_QUOTE = 5
    TTL_MARGIN = 30
    TTL_POSITIONS = 10

    def __init__(self, cache_dir: str = "logs/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._l1: Dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_timestamp)
        self.clear_expired()

    def _hash_key(self, key: str) -> str:
        """MD5 hash of the key to make a safe filename."""
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def _get_paths(self, key: str) -> tuple[Path, Path]:
        """Return (data_path, meta_path) for L2 storage."""
        h = self._hash_key(key)
        return self.cache_dir / h, self.cache_dir / f"{h}.meta.json"

    # ── General Object caching (JSON) ──────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        """Fetch general object from L1, fallback to L2."""
        now = time.time()
        
        # Check L1
        if key in self._l1:
            val, expiry = self._l1[key]
            if now < expiry:
                logger.debug(f"[Cache L1 HIT] {key}")
                return val
            # L1 expired, delete it
            del self._l1[key]

        # Check L2
        data_path, meta_path = self._get_paths(key)
        json_path = data_path.with_suffix(".json")
        if json_path.exists() and meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                
                if now < meta.get("expiry", 0):
                    with open(json_path, "r", encoding="utf-8") as f:
                        val = json.load(f)
                    
                    # Backpopulate L1
                    self._l1[key] = (val, meta["expiry"])
                    logger.debug(f"[Cache L2 HIT] {key}")
                    return val
                else:
                    # L2 expired
                    logger.debug(f"[Cache L2 EXPIRED] {key}")
                    self._delete_files(json_path, meta_path)
            except Exception as e:
                logger.warning(f"Error reading L2 JSON cache for {key}: {e}")
                self._delete_files(json_path, meta_path)

        logger.debug(f"[Cache MISS] {key}")
        return None

    def set(self, key: str, value: Any, ttl: int) -> None:
        """Write general object to L1 and L2."""
        expiry = time.time() + ttl
        self._l1[key] = (value, expiry)

        data_path, meta_path = self._get_paths(key)
        json_path = data_path.with_suffix(".json")
        try:
            # Write data file
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(value, f, default=str)
            # Write meta file
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({"expiry": expiry, "type": "json", "key": key}, f)
        except Exception as e:
            logger.error(f"Failed to write cache L2 files for {key}: {e}")

    # ── DataFrame caching (Parquet) ────────────────────────────────────────────

    def get_df(self, key: str) -> Optional[pd.DataFrame]:
        """Fetch DataFrame from L1, fallback to L2 parquet."""
        now = time.time()
        
        # Check L1
        if key in self._l1:
            df, expiry = self._l1[key]
            if now < expiry:
                logger.debug(f"[Cache L1 DataFrame HIT] {key}")
                return df
            del self._l1[key]

        # Check L2 Parquet
        data_path, meta_path = self._get_paths(key)
        pq_path = data_path.with_suffix(".parquet")
        if pq_path.exists() and meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                
                if now < meta.get("expiry", 0):
                    df = pd.read_parquet(pq_path)
                    # Backpopulate L1
                    self._l1[key] = (df, meta["expiry"])
                    logger.debug(f"[Cache L2 DataFrame HIT] {key}")
                    return df
                else:
                    logger.debug(f"[Cache L2 DataFrame EXPIRED] {key}")
                    self._delete_files(pq_path, meta_path)
            except Exception as e:
                logger.warning(f"Error reading L2 Parquet cache for {key}: {e}")
                self._delete_files(pq_path, meta_path)

        logger.debug(f"[Cache DataFrame MISS] {key}")
        return None

    def set_df(self, key: str, df: pd.DataFrame, ttl: int) -> None:
        """Write DataFrame to L1 and L2 parquet."""
        expiry = time.time() + ttl
        self._l1[key] = (df, expiry)

        data_path, meta_path = self._get_paths(key)
        pq_path = data_path.with_suffix(".parquet")
        try:
            # Write parquet
            df.to_parquet(pq_path, engine="pyarrow")
            # Write meta file
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "expiry": expiry,
                    "type": "parquet",
                    "rows": len(df),
                    "key": key
                }, f)
        except Exception as e:
            logger.error(f"Failed to write cache L2 Parquet for {key}: {e}")

    # ── Utilities ──────────────────────────────────────────────────────────────

    def invalidate(self, key: str) -> None:
        """Clear cache entries for a specific key."""
        if key in self._l1:
            del self._l1[key]
        data_path, meta_path = self._get_paths(key)
        self._delete_files(data_path.with_suffix(".json"), meta_path)
        self._delete_files(data_path.with_suffix(".parquet"), meta_path)

    def _delete_files(self, *paths: Path) -> None:
        for p in paths:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def clear_expired(self) -> None:
        """Loop through all L2 files on startup/cleanup and remove expired items."""
        logger.info("Cleaning expired L2 cache files on startup...")
        now = time.time()
        
        # Clean L1
        self._l1 = {k: (v, exp) for k, (v, exp) in self._l1.items() if now < exp}

        # Clean L2 disk
        if not self.cache_dir.exists():
            return

        for meta_file in self.cache_dir.glob("*.meta.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                
                if now >= meta.get("expiry", 0):
                    # Cache expired, delete data file and meta file
                    h_name = meta_file.name.replace(".meta.json", "")
                    self._delete_files(meta_file)
                    self._delete_files(self.cache_dir / f"{h_name}.json")
                    self._delete_files(self.cache_dir / f"{h_name}.parquet")
            except Exception as e:
                # Corrupt meta file, delete it
                self._delete_files(meta_file)

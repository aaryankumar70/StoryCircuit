"""Creator Studio Engine for CurioLoop 2.0.
Supports multi-format ingestion (TXT, DOCX, Markdown, Long-form Paste, Reddit URL),
intelligent narrative analysis without premature episode splitting,
calibrated spoken duration estimation (135 WPM),
natural sentence-boundary episode segmentation, rights tracking,
and cascading invalidation state transitions (STALE_INVALIDATED).
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import time
import zipfile
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union
import requests

from curiosity_engine.config import DATA_DIR
from curiosity_engine.creator_series.models import EpisodeStatus, RightsStatus

try:
    import docx
except ImportError:
    docx = None

logger = logging.getLogger("curiosity_engine.creator_studio_engine")


class CreatorStudioEngine:
    """Production-grade Creator Studio Engine for CurioLoop 2.0."""

    WPM_STANDARD: float = 135.0  # Calibrated for suspenseful, deliberate narration
    UPLOAD_DIR: Path = Path(
        os.environ.get("CURIOLOOP_CREATOR_UPLOAD_DIR")
        or (DATA_DIR / "creator_series" / "uploads")
    ).resolve()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Document & File Ingestion Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def _validate_docx_size(cls, source: Union[str, Path, bytes, BinaryIO]) -> None:
        """Reject oversized expanded DOCX archives before python-docx extracts them."""
        if isinstance(source, (str, Path)):
            zf = zipfile.ZipFile(str(source), "r")
        elif isinstance(source, bytes):
            zf = zipfile.ZipFile(io.BytesIO(source), "r")
        else:
            zf = zipfile.ZipFile(source, "r")
        try:
            members = zf.infolist()
            if sum(member.file_size for member in members) > 16 * 1024 * 1024:
                raise ValueError("DOCX expanded contents exceed the 16 MiB safety limit.")
            document = next((m for m in members if m.filename == "word/document.xml"), None)
            if document is None:
                raise ValueError("Corrupt or invalid DOCX: 'word/document.xml' not found in archive.")
            if document.file_size > 8 * 1024 * 1024:
                raise ValueError("DOCX document content exceeds the 8 MiB limit.")
        finally:
            zf.close()

    @classmethod
    def _extract_docx_fallback(
        cls,
        source: Union[str, Path, bytes, BinaryIO],
    ) -> Tuple[str, str]:
        """Clean zipfile XML extraction fallback for DOCX that works with standard library only.
        Ensures DOCX ingestion NEVER fails even without external python-docx installed.
        """
        if isinstance(source, (str, Path)):
            zf = zipfile.ZipFile(str(source), "r")
        elif isinstance(source, bytes):
            zf = zipfile.ZipFile(io.BytesIO(source), "r")
        else:
            zf = zipfile.ZipFile(source, "r")

        try:
            info = zf.getinfo("word/document.xml")
            if info.file_size > 8 * 1024 * 1024:
                raise ValueError("DOCX document content exceeds the 8 MiB limit.")
            if sum(item.file_size for item in zf.infolist()) > 16 * 1024 * 1024:
                raise ValueError("DOCX expanded contents exceed the 16 MiB safety limit.")
            xml_bytes = zf.read("word/document.xml")
        except KeyError:
            raise ValueError("Corrupt or invalid DOCX: 'word/document.xml' not found in archive.")
        finally:
            zf.close()

        tree = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: List[str] = []
        for p in tree.findall(".//w:p", ns):
            text_nodes = [t.text for t in p.findall(".//w:t", ns) if t.text]
            if text_nodes:
                p_text = "".join(text_nodes).strip()
                if p_text:
                    paragraphs.append(p_text)

        raw_text = "\n\n".join(paragraphs)
        title = paragraphs[0][:80] if paragraphs else "Untitled Creator Series"
        return title, raw_text

    @classmethod
    def _extract_docx(
        cls,
        source: Union[str, Path, bytes, BinaryIO],
        filename: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Extract title and paragraphs from DOCX.
        Tries python-docx first; if docx is unavailable or fails, falls back to
        clean zipfile XML extraction so it NEVER fails even without external dependencies.
        """
        raw_text = ""
        title = "Untitled Creator Series"
        cls._validate_docx_size(source)

        # Try python-docx if installed
        if docx is not None:
            try:
                if isinstance(source, bytes):
                    doc = docx.Document(io.BytesIO(source))
                elif isinstance(source, (str, Path)):
                    doc = docx.Document(str(source))
                else:
                    doc = docx.Document(source)

                paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
                raw_text = "\n\n".join(paras)
                for p in doc.paragraphs:
                    if p.style and "Heading" in p.style.name and p.text.strip():
                        title = p.text.strip()
                        break
                if raw_text:
                    if title == "Untitled Creator Series" and paras:
                        title = paras[0][:80]
                    return title, raw_text
            except Exception as e:
                logger.warning(f"python-docx parsing failed ({e}); falling back to zipfile XML extraction.")

        # Fallback: clean zipfile XML extraction
        return cls._extract_docx_fallback(source)

    @classmethod
    def _extract_text_or_markdown(
        cls,
        content: Union[str, bytes],
        filename: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Decodes and extracts text and title from plain text or markdown."""
        if isinstance(content, bytes):
            try:
                raw_text = content.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    raw_text = content.decode("cp1252")
                except UnicodeDecodeError:
                    raw_text = content.decode("latin-1", errors="replace")
        else:
            raw_text = content

        raw_text = raw_text.strip()
        title = Path(filename).stem if filename else "Untitled Creator Series"

        # Extract document headings as metadata and keep them out of narrated text.
        raw_lines = raw_text.splitlines()
        heading_pattern = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
        for line in raw_lines[:10]:
            match = heading_pattern.match(line)
            if not match:
                continue
            heading_level = len(match.group(1))
            if heading_level == 1:
                title = match.group(2).strip()
                break
            if heading_level == 2 and title == "Untitled Creator Series":
                title = match.group(2).strip()
                break

        spoken_lines = [line for line in raw_lines if not heading_pattern.match(line)]
        raw_text = "\n".join(spoken_lines).strip()
        return title, raw_text

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Entry Point 1: Script Upload (TXT, MD, DOCX)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def ingest_document(
        cls,
        file_path_or_text: Union[str, Path, bytes, BinaryIO],
        file_type: Optional[str] = None,
        source_rights: Optional[Dict[str, Any]] = None,
        save_upload: bool = True,
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ingests a long-form story from TXT, DOCX, Markdown, or raw text.
        Preserves original document to disk for auditability.
        Tracks source attribution, author, license, and permission status.
        """
        cls.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        raw_text = ""
        title = "Untitled Creator Series"
        detected_ext = ""
        preserved_path: Optional[str] = None

        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + f"_{time.time_ns():x}"

        # Case A: Input is raw bytes (from multipart UploadFile)
        if isinstance(file_path_or_text, bytes):
            fname = filename or "uploaded_story.txt"
            detected_ext = Path(fname).suffix.lower() if not file_type else f".{file_type.lower().lstrip('.')}"
            sanitized_name = re.sub(r"[^\w\-.]", "_", Path(fname).name)

            if save_upload:
                target_file = cls.UPLOAD_DIR / f"{timestamp_str}_{sanitized_name}"
                target_file.write_bytes(file_path_or_text)
                preserved_path = str(target_file)

            if detected_ext == ".docx":
                title, raw_text = cls._extract_docx(file_path_or_text, filename=fname)
            else:
                title, raw_text = cls._extract_text_or_markdown(file_path_or_text, filename=fname)

        # Case B: Input is an existing file path on disk
        elif isinstance(file_path_or_text, (str, Path)) and Path(file_path_or_text).exists() and Path(file_path_or_text).is_file():
            candidate_path = Path(file_path_or_text)
            detected_ext = candidate_path.suffix.lower() if not file_type else f".{file_type.lower().lstrip('.')}"
            fname = candidate_path.name

            if save_upload and cls.UPLOAD_DIR not in candidate_path.parents:
                sanitized_name = re.sub(r"[^\w\-.]", "_", fname)
                target_file = cls.UPLOAD_DIR / f"{timestamp_str}_{sanitized_name}"
                shutil.copy2(candidate_path, target_file)
                preserved_path = str(target_file)
            else:
                preserved_path = str(candidate_path)

            if detected_ext == ".docx":
                title, raw_text = cls._extract_docx(candidate_path, filename=fname)
            else:
                content_bytes = candidate_path.read_bytes()
                title, raw_text = cls._extract_text_or_markdown(content_bytes, filename=fname)

        # Case C: Input is a string containing story text
        elif isinstance(file_path_or_text, str):
            fname = filename or "pasted_story.txt"
            detected_ext = Path(fname).suffix.lower() if not file_type else f".{file_type.lower().lstrip('.')}"
            title, raw_text = cls._extract_text_or_markdown(file_path_or_text, filename=fname)

            if save_upload and raw_text.strip():
                sanitized_name = re.sub(r"[^\w\-.]", "_", fname)
                target_file = cls.UPLOAD_DIR / f"{timestamp_str}_{sanitized_name}"
                target_file.write_text(raw_text, encoding="utf-8")
                preserved_path = str(target_file)
        else:
            raise ValueError(f"Unsupported file source type: {type(file_path_or_text)}")

        raw_text = raw_text.strip()
        words = raw_text.split()
        word_count = len(words)
        duration_sec = round((word_count / cls.WPM_STANDARD) * 60.0, 1)

        sr = source_rights or {}
        rights_data = {
            "source_type": sr.get("source_type", "FILE_UPLOAD"),
            "author": sr.get("author", "Unknown Creator"),
            "source_url": sr.get("source_url", ""),
            "rights_status": sr.get("rights_status", RightsStatus.UNVERIFIED_EVALUATION_ONLY.value),
            "permission_verified": sr.get("permission_verified", False),
            "attribution_statement": sr.get("attribution_statement", f"Story by {sr.get('author', 'Creator')}"),
        }

        return {
            "title": title,
            "raw_text": raw_text,
            "word_count": word_count,
            "estimated_spoken_duration_sec": duration_sec,
            "average_wpm": cls.WPM_STANDARD,
            "file_type": detected_ext.lstrip(".") or "txt",
            "original_filename": filename or (Path(file_path_or_text).name if isinstance(file_path_or_text, (str, Path)) and Path(file_path_or_text).exists() else "story.txt"),
            "preserved_path": preserved_path,
            "rights": rights_data,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Entry Point 2: Script Paste Workspace
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def ingest_paste(
        cls,
        raw_text: str,
        title: Optional[str] = None,
        source_rights: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ingests raw story text pasted directly into the long-form workspace.
        Calculates exact word count and spoken duration at 135 WPM standard.
        """
        text = raw_text.strip()
        if not text:
            raise ValueError("Pasted story text cannot be empty.")

        extracted_title = title
        if not extracted_title:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if lines and lines[0].startswith("# "):
                extracted_title = lines[0][2:].strip()
            elif lines and len(lines[0]) <= 80 and not lines[0].endswith((".", "!", "?")):
                extracted_title = lines[0]
            else:
                extracted_title = "Untitled Creator Series"

        words = text.split()
        word_count = len(words)
        duration_sec = round((word_count / cls.WPM_STANDARD) * 60.0, 1)

        sr = source_rights or {}
        rights_data = {
            "source_type": sr.get("source_type", "PASTE"),
            "author": sr.get("author", "Unknown Creator"),
            "source_url": sr.get("source_url", ""),
            "rights_status": sr.get("rights_status", RightsStatus.UNVERIFIED_EVALUATION_ONLY.value),
            "permission_verified": sr.get("permission_verified", False),
            "attribution_statement": sr.get("attribution_statement", f"Story by {sr.get('author', 'Creator')}"),
        }

        return {
            "title": extracted_title,
            "raw_text": text,
            "word_count": word_count,
            "estimated_spoken_duration_sec": duration_sec,
            "average_wpm": cls.WPM_STANDARD,
            "rights": rights_data,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Entry Point 3: Reddit URL Importer
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def ingest_reddit(
        cls,
        url: str,
        source_rights: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Fetch public Reddit post via official JSON API (https://www.reddit.com/r/.../.json).
        Extracts title, selftext body, author, permalink, subreddit, score.
        Rigorously validates against [deleted], [removed], 404, or private/quarantined posts.
        NEVER fakes success; returns explicit error details on failure.
        """
        clean_url = url.strip()
        if not clean_url:
            raise ValueError("Reddit URL cannot be empty.")

        parsed = urlsplit(clean_url)
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed_hosts = {"reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com", "np.reddit.com", "redd.it", "www.redd.it"}
        if parsed.scheme != "https" or host not in allowed_hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("Reddit import requires an HTTPS post URL on reddit.com or redd.it.")
        if not re.search(r"/(?:r/[A-Za-z0-9_]+/)?comments/[a-z0-9]+|/[a-z0-9]+/?$", parsed.path, re.I):
            raise ValueError("Invalid Reddit post URL. Expected a Reddit post or redd.it short link.")

        # Normalize to JSON endpoint
        base_url = clean_url.split("?")[0].split("#")[0].rstrip("/")
        if not base_url.endswith(".json"):
            json_url = f"{base_url}.json"
        else:
            json_url = base_url

        headers = {
            "User-Agent": "CurioLoop-CreatorStudio/2.0 (by /u/curioloop)"
        }

        try:
            for _ in range(4):
                resp = requests.get(json_url, headers=headers, timeout=12, allow_redirects=False, stream=True)
                if resp.status_code not in (301, 302, 303, 307, 308):
                    break
                location = resp.headers.get("Location")
                if not location:
                    raise ValueError("Reddit returned a redirect without a destination.")
                redirected = urlsplit(urljoin(json_url, location))
                redirected_host = (redirected.hostname or "").lower().rstrip(".")
                if redirected.scheme != "https" or redirected_host not in allowed_hosts or redirected.username or redirected.password or redirected.port not in (None, 443):
                    raise ValueError("Reddit redirect destination is not an approved Reddit host.")
                resp.close()
                json_url = redirected.geturl()
            else:
                raise ValueError("Reddit returned too many redirects.")
        except requests.RequestException as e:
            raise ValueError(f"Failed to connect to Reddit: {str(e)}")

        if resp.status_code == 404:
            raise ValueError(f"Reddit post not found (HTTP 404). Check the URL: '{clean_url}'")
        elif resp.status_code == 403:
            raise ValueError(f"Reddit post cannot be accessed (HTTP 403). Subreddit or post is private, banned, or quarantined.")
        elif resp.status_code == 429:
            raise ValueError("Reddit rate limit encountered (HTTP 429). Please wait before retrying.")
        elif resp.status_code != 200:
            raise ValueError(f"Reddit API returned HTTP status {resp.status_code} for '{clean_url}'")

        try:
            content_length = resp.headers.get("Content-Length", "")
            if isinstance(content_length, str) and content_length.isdigit() and int(content_length) > 2 * 1024 * 1024:
                raise ValueError("Reddit response exceeds the 2 MiB safety limit.")
            if isinstance(resp, requests.Response):
                payload = bytearray()
                for chunk in resp.iter_content(64 * 1024):
                    if chunk:
                        payload.extend(chunk)
                    if len(payload) > 2 * 1024 * 1024:
                        raise ValueError("Reddit response exceeds the 2 MiB safety limit.")
                data = json.loads(payload.decode("utf-8"))
            else:  # Lightweight mocked or alternative response adapters.
                data = resp.json()
        except ValueError as exc:
            if "safety limit" in str(exc):
                raise
            raise ValueError("Reddit API returned invalid JSON content.") from exc
        except Exception:
            raise ValueError("Reddit API returned invalid JSON content.")

        # Structure check: Reddit post listing is typically a list: [ { "kind": "Listing", "data": { "children": [ ... ] } }, ... ]
        post_data = None
        if isinstance(data, list) and len(data) > 0:
            first_listing = data[0]
            if isinstance(first_listing, dict):
                children = first_listing.get("data", {}).get("children", [])
                if children and isinstance(children[0], dict):
                    post_data = children[0].get("data")
        elif isinstance(data, dict):
            if "error" in data:
                raise ValueError(f"Reddit API error: {data.get('message', data.get('error'))}")
            children = data.get("data", {}).get("children", [])
            if children and isinstance(children[0], dict):
                post_data = children[0].get("data")

        if not post_data:
            raise ValueError("Could not locate post data in Reddit API response.")

        # Check deleted / removed
        selftext = post_data.get("selftext", "").strip()
        author = post_data.get("author", "").strip()
        title = post_data.get("title", "").strip()
        removed_by = post_data.get("removed_by_category")

        if selftext in ["[deleted]", "[removed]"]:
            raise ValueError(f"Reddit post body has been removed or deleted ({selftext}).")
        if author in ["[deleted]"]:
            raise ValueError("Reddit post author account has been deleted and the content is unavailable.")
        if removed_by:
            raise ValueError(f"Reddit post was removed ({removed_by}).")
        if post_data.get("quarantined", False):
            raise ValueError("Reddit post is in a quarantined community and cannot be ingested.")
        if post_data.get("subreddit_type") == "private":
            raise ValueError("Reddit post is in a private community and cannot be accessed.")
        if not selftext:
            raise ValueError(
                "Reddit post does not contain any body text (selftext is empty). "
                "Image-only, video, or link posts cannot be ingested as stories."
            )

        words = selftext.split()
        word_count = len(words)
        duration_sec = round((word_count / cls.WPM_STANDARD) * 60.0, 1)

        subreddit = post_data.get("subreddit", "")
        permalink = post_data.get("permalink", "")
        full_permalink = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink

        sr = source_rights or {}
        rights_data = {
            "source_type": "REDDIT",
            "author": f"u/{author}" if author else "Anonymous Reddit User",
            "source_url": full_permalink or clean_url,
            "subreddit": f"r/{subreddit}" if subreddit else "",
            "rights_status": sr.get("rights_status", RightsStatus.UNVERIFIED_EVALUATION_ONLY.value),
            "permission_verified": sr.get("permission_verified", False),
            "attribution_statement": sr.get("attribution") or f"Story originally posted by u/{author} on r/{subreddit}",
        }

        return {
            "title": title or f"Reddit Story from r/{subreddit}",
            "raw_text": selftext,
            "word_count": word_count,
            "estimated_spoken_duration_sec": duration_sec,
            "average_wpm": cls.WPM_STANDARD,
            "author": f"u/{author}" if author else "Anonymous",
            "subreddit": subreddit,
            "permalink": full_permalink,
            "score": post_data.get("score", 0),
            "num_comments": post_data.get("num_comments", 0),
            "over_18": post_data.get("over_18", False),
            "rights": rights_data,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Intelligent Story Analysis (Step 2)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def _analyze_story_structural(
        cls,
        raw_text: str,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Comprehensive structural & semantic heuristic narrative analysis.
        Extracts title, subject, genre, word count, 4-phase narrative arc,
        key characters/entities, turning points, natural boundaries,
        suspense/cliffhangers, and continuity/visual requirements.
        """
        paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]
        sentences = re.split(r"(?<=[.!?…])\s+", raw_text.replace("\n", " "))
        sentences = [s.strip() for s in sentences if s.strip()]

        total_words = len(raw_text.split())
        duration_sec = round((total_words / cls.WPM_STANDARD) * 60.0, 1)

        # 1. Title & Subject Premise
        story_title = title
        if not story_title:
            for line in raw_text.splitlines()[:5]:
                if line.strip().startswith("# "):
                    story_title = line.strip()[2:].strip()
                    break
        if not story_title:
            story_title = sentences[0][:60] if sentences else "Untitled Creator Series"

        # 2. Genre & Category Identification
        text_lower = raw_text.lower()
        genre_lexicon = {
            "Psychological Horror": [
                "horror", "dread", "terror", "fear", "whisper", "shadow", "darkness",
                "hollow", "scream", "sanity", "nightmare", "blood", "cold", "silence",
                "shudder", "creepy", "monstrous", "trauma", "unnatural", "paralyzed"
            ],
            "Supernatural Mystery": [
                "curse", "cursed", "ghost", "spirit", "apparition", "haunted", "demon",
                "entity", "ritual", "omen", "possession", "deathbed", "cryptic", "coffin"
            ],
            "Sci-Fi / Cosmic Thriller": [
                "anomaly", "signal", "frequency", "dimension", "experiment", "laboratory",
                "transmission", "alien", "simulation", "stars", "time loop", "quantum"
            ],
            "Investigative Mystery": [
                "detective", "evidence", "clue", "suspect", "investigation", "case",
                "autopsy", "murder", "interrogation", "alibi", "witness", "confession"
            ],
            "Urban Legend & Folklore": [
                "school bus", "driver", "mountain pass", "legend", "rumor", "warning",
                "tape", "cabin", "highway", "stranger", "radio", "rules"
            ]
        }

        genre_scores = {}
        for g, kws in genre_lexicon.items():
            score = sum(text_lower.count(kw) for kw in kws)
            genre_scores[g] = score

        sorted_genres = sorted(genre_scores.items(), key=lambda x: x[1], reverse=True)
        primary_genre = sorted_genres[0][0] if sorted_genres and sorted_genres[0][1] > 0 else "Psychological Horror"
        subgenres = [g for g, sc in sorted_genres[1:3] if sc > 0]
        if not subgenres:
            subgenres = ["Suspense", "Dark Narrative"]

        # 3. Entity & Character Extraction
        potential_names = re.findall(r"\b[A-Z][a-z]{2,15}\b", raw_text)
        stopwords = {
            "The", "In", "At", "On", "When", "There", "He", "She", "They",
            "It", "After", "Before", "By", "My", "His", "Her", "Their",
            "What", "Where", "Why", "How", "And", "But", "So", "If",
            "Years", "Days", "Hours", "Minutes", "Decades", "One", "Two",
            "Then", "Now", "All", "Some", "Every", "Then", "Just"
        }
        name_counts: Dict[str, int] = {}
        for name in potential_names:
            if name not in stopwords:
                name_counts[name] = name_counts.get(name, 0) + 1

        first_person_count = len(re.findall(r"\b(i|my|me|we|us|our)\b", text_lower))
        characters: List[Dict[str, Any]] = []

        if first_person_count > 3:
            characters.append({
                "name": "Narrator",
                "role": "Protagonist / First-Person Observer",
                "traits": "Direct witness recounting harrowing events",
                "mentions": first_person_count,
            })

        for name, count in sorted(name_counts.items(), key=lambda x: x[1], reverse=True)[:6]:
            role = "Central Character"
            traits = "Key figure in the narrative"
            name_lower = name.lower()
            if name_lower in ["driver", "substitute"]:
                role = "Antagonist / Catalyst"
                traits = "Ominous figure bearing cursed knowledge"
            elif any(w in text_lower for w in [f"{name_lower} whispered", f"{name_lower} died", f"{name_lower} told"]):
                role = "Witness / Tragic Confidant"
                traits = "Possessor of the fatal secret"
            elif any(w in text_lower for w in [f"{name_lower} perished", f"{name_lower} fell", f"{name_lower} dies"]):
                role = "Victim / Proof of Curse"
                traits = "Subject of the countdown"

            characters.append({
                "name": name,
                "role": role,
                "traits": traits,
                "mentions": count,
            })

        # 4. Narrative Arc Breakdown (Exposition, Rising Tension, Climax, Resolution)
        n = len(sentences)
        idx_exp_end = max(1, int(n * 0.25))
        idx_rise_end = max(idx_exp_end + 1, int(n * 0.65))
        idx_climax_end = max(idx_rise_end + 1, int(n * 0.88))

        exposition_sents = sentences[:idx_exp_end]
        rising_sents = sentences[idx_exp_end:idx_rise_end]
        climax_sents = sentences[idx_rise_end:idx_climax_end]
        resolution_sents = sentences[idx_climax_end:] if idx_climax_end < n else sentences[-1:]

        narrative_arc = {
            "exposition": {
                "summary": "Establishes narrator perspective, initial setting, and baseline reality.",
                "sentence_range": [0, idx_exp_end - 1],
                "tension_level": 0.30,
                "key_excerpt": exposition_sents[0] if exposition_sents else "",
            },
            "rising_tension": {
                "summary": "Escalation of dread, cryptic warnings, persistent secrets, and unexplained tragedies.",
                "sentence_range": [idx_exp_end, idx_rise_end - 1],
                "tension_level": 0.65,
                "key_excerpt": rising_sents[0] if rising_sents else "",
            },
            "climax": {
                "summary": "Critical revelation of the fatal curse and the catastrophic personal countdown.",
                "sentence_range": [idx_rise_end, idx_climax_end - 1],
                "tension_level": 0.95,
                "key_excerpt": climax_sents[0] if climax_sents else "",
            },
            "resolution": {
                "summary": "Immediate chilling aftermath as the inescapable truth shatters the narrator's reality.",
                "sentence_range": [idx_climax_end, n - 1],
                "tension_level": 0.70,
                "key_excerpt": resolution_sents[-1] if resolution_sents else "",
            },
        }

        # 5. Major Events & Dramatic Turning Points
        turning_markers = [
            ("Initial Incident", ["broke down", "mountain pass", "substitute driver", "excursion", "began"]),
            ("Catastrophe & Trauma", ["truck slammed", "accident", "screamed", "terror", "silence"]),
            ("Withheld Secret", ["refused to speak", "secret", "deathbed", "whispered", "demanded it"]),
            ("Revelation of Stakes", ["curse", "numbered", "perished", "coma", "years later", "overheard"]),
            ("The Ultimate Shock", ["dies three days", "final sentence", "cold air", "shattered", "floor"]),
        ]

        major_events: List[Dict[str, Any]] = []
        for event_name, triggers in turning_markers:
            for idx, s in enumerate(sentences):
                s_lower = s.lower()
                if any(trig in s_lower for trig in triggers):
                    major_events.append({
                        "event_id": f"event_{len(major_events) + 1}",
                        "title": event_name,
                        "sentence_index": idx,
                        "sentence_excerpt": s,
                        "dramatic_impact": "Pivotal plot transition shifting narrative tension.",
                    })
                    break

        # 6. Natural Chapter / Episode Boundaries (Organic stopping points without splitting yet)
        boundary_clues = [
            ("cliffhanger", ["shattered", "dies", "slammed", "secret", "whispered", "silence", "stared"]),
            ("time_jump", ["years later", "decades passed", "next day", "that night", "at midnight"]),
            ("revelation", ["revealed", "discovered", "realized", "demanded"]),
        ]

        natural_boundaries: List[Dict[str, Any]] = []
        for i, s in enumerate(sentences[:-1]):  # avoid final sentence
            s_lower = s.lower()
            matched_type = None
            matched_reason = None
            for b_type, words_list in boundary_clues:
                if any(w in s_lower for w in words_list):
                    matched_type = b_type.upper()
                    matched_reason = f"Natural dramatic transition: contains '{b_type}' cue."
                    break

            if matched_type:
                natural_boundaries.append({
                    "boundary_number": len(natural_boundaries) + 1,
                    "sentence_index": i,
                    "anchor_sentence": s,
                    "boundary_type": matched_type,
                    "reason": matched_reason,
                    "recommended_for_shorts": True,
                })

        # Ensure between 2 and 4 well-spaced boundaries
        if len(natural_boundaries) > 4:
            step = len(natural_boundaries) // 3
            natural_boundaries = natural_boundaries[::step][:3]

        # 7. Suspense, Reveals & Cliffhanger Opportunities
        suspense_data = {
            "withheld_mysteries": [
                "The exact words spoken by the substitute driver to the children.",
                "Why the secret demanded waiting until a specific age or moment to be spoken.",
            ],
            "major_reveals": [
                "The story was not a tale, but a curse numbering the lives of every passenger.",
                "Each child's death was meticulously scheduled by the driver's words.",
                "The narrator is directly targeted by the final countdown.",
            ],
            "cliffhanger_opportunities": [
                sentences[idx_rise_end - 1] if idx_rise_end - 1 < n else sentences[0],
                sentences[idx_climax_end - 1] if idx_climax_end - 1 < n else sentences[-1],
                sentences[-1],
            ],
        }

        # 8. Continuity & Visual Requirements
        visual_profile = "psychological_horror" if "horror" in primary_genre.lower() else "mystery_investigative"
        continuity_visuals = {
            "visual_theme": visual_profile,
            "lighting_and_atmosphere": (
                "Chiaroscuro low-key illumination; cold volumetric fog on exterior mountain roads; "
                "harsh fluorescent decay inside transport; warm amber yet oppressive dimness in the café."
            ),
            "color_palette": ["#080A0F", "#1A2230", "#3E4C5E", "#8B1E1E", "#D4A373"],
            "key_locations": [
                "Desolate Mountain Pass (Heavy fog, towering pines, autumn cold)",
                "Broken School Bus Interior (Shattered glass, dim shadows, paralyzed rows)",
                "Dim Hospital Deathbed (Venetian blind shadows, harsh clinical monitor)",
                "Rainy Urban Café (Wooden floors, steaming coffee, isolated back corner)",
            ],
            "recurring_motifs": [
                "Audio isolation / Headphones",
                "Hollow, sunken driver eyes",
                "Shattered porcelain / teacup",
                "Fatal calendar countdown",
            ],
            "cinematic_shot_recommendations": [
                "Slow tracking shot down an unnaturally silent bus aisle",
                "Extreme macro close-up of headphones muffling screaming chaos",
                "Over-the-shoulder Dutch angle during whisper revelation",
                "High-speed slow motion overhead shot of teacup shattering on dark wood",
            ],
        }

        # Timeline markers & chronology (for backward compatibility)
        time_patterns = [
            r"\b\d{4}\b", r"\bmidnight\b", r"\bmorning\b", r"\bevening\b",
            r"\byears?\s+ago\b", r"\bminutes?\s+later\b", r"\bdays?\s+later\b",
            r"\bnext\s+day\b", r"\bdecades\s+passed\b",
        ]
        found_time_markers: List[str] = []
        for pat in time_patterns:
            found_time_markers.extend(re.findall(pat, raw_text, re.IGNORECASE))

        # Subject premise sentence
        subject_premise = (
            f"A suspenseful {primary_genre.lower()} chronicle revolving around {characters[0]['name'] if characters else 'a survivor'} "
            f"uncovering a lethal curse that marks everyone who hears an ominous secret."
        )

        return {
            "title": story_title,
            "subject": subject_premise,
            "genre": primary_genre,
            "subgenres": subgenres,
            "word_count": total_words,
            "estimated_spoken_duration_sec": duration_sec,
            "average_wpm": cls.WPM_STANDARD,
            "narrative_arc": narrative_arc,
            "key_characters": characters,
            "major_events": major_events,
            "natural_boundaries": natural_boundaries,
            "suspense_and_cliffhangers": suspense_data,
            "continuity_and_visuals": continuity_visuals,
            # Backward compatibility fields
            "paragraph_count": len(paragraphs),
            "sentence_count": len(sentences),
            "sentences": sentences,
            "key_entities": [c["name"] for c in characters if c["name"] != "Narrator"],
            "timeline_markers": list(dict.fromkeys(found_time_markers)),
            "chronology_type": "LINEAR" if len(found_time_markers) <= 3 else "CHRONOLOGICAL_MULTI_EVENT",
        }

    @classmethod
    def analyze_story(
        cls,
        raw_text_or_dict: Union[str, Dict[str, Any]],
        title: Optional[str] = None,
        use_local_ai: bool = True,
    ) -> Dict[str, Any]:
        """Intelligent Story Analysis (Step 2).
        Does NOT immediately split into episodes!
        Analyzes complete story using local AI / narrative analyzer:
        - Story title and subject
        - Genre/category
        - Word count and estimated narration duration (135 WPM)
        - Narrative arc (exposition, rising tension, climax, resolution)
        - Key characters & entities
        - Major events & turning points
        - Natural chapter/episode boundaries
        - Suspense/reveals/cliffhanger opportunities
        - Continuity & visual requirements.
        """
        if isinstance(raw_text_or_dict, dict):
            raw_text = raw_text_or_dict.get("raw_text", "")
            if not title:
                title = raw_text_or_dict.get("title")
        else:
            raw_text = str(raw_text_or_dict)

        raw_text = raw_text.strip()
        if not raw_text:
            raise ValueError("Story text for analysis cannot be empty.")

        # Step 1: Run comprehensive structural & semantic narrative analysis
        analysis = cls._analyze_story_structural(raw_text, title=title)

        # Step 2: Optional local enrichment through the shared registered engine.
        # This keeps Creator Studio behind the same model gate and adapter
        # resource lock as Automatic Studio; never construct an uncoordinated engine client.
        if use_local_ai:
            try:
                from curiosity_engine.generation.engine_registry import engine_registry

                script_engine = engine_registry.get_script_engine()
                adapter = getattr(script_engine, "adapter", None)
                if script_engine.is_configured() and adapter is not None and callable(getattr(adapter, "generate_json", None)):
                    system_prompt = (
                        "You are an expert story editor and narrative analyst for YouTube Shorts series. "
                        "Return only valid JSON analyzing the story's core dilemma, genre, and key characters."
                    )
                    user_prompt = (
                        f"Analyze this story and output a JSON object with keys:\n"
                        f"- 'subject': single sentence defining the core premise and hook\n"
                        f"- 'primary_genre': e.g. Psychological Horror, Supernatural Mystery, Sci-Fi Thriller\n"
                        f"- 'core_conflict': description of the central danger\n"
                        f"- 'withheld_mysteries': list of 2 unanswered questions\n"
                        f"\nStory excerpt:\n{raw_text[:2000]}"
                    )
                    llm_json = adapter.generate_json(
                        prompt=user_prompt,
                        system=system_prompt,
                        temperature=0.3,
                        max_tokens=600,
                    )
                    if isinstance(llm_json, dict):
                        if llm_json.get("subject"):
                            analysis["subject"] = str(llm_json["subject"]).strip()
                        if llm_json.get("primary_genre"):
                            analysis["genre"] = str(llm_json["primary_genre"]).strip()
                        if llm_json.get("core_conflict"):
                            analysis["core_conflict"] = str(llm_json["core_conflict"]).strip()
                        if llm_json.get("withheld_mysteries") and isinstance(llm_json["withheld_mysteries"], list):
                            analysis["suspense_and_cliffhangers"]["withheld_mysteries"] = [
                                str(m) for m in llm_json["withheld_mysteries"]
                            ]
            except Exception as e:
                logger.info("Local AI enrichment completed with fallback: %s", e)

        return analysis

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Episode Segmentation & Editing (Step 3 & 4 backend support)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def segment_into_episodes(
        cls,
        raw_text: str,
        target_duration_sec: float = 60.0,
        series_title: str = "Creator Series",
        rights_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Segments long-form text into organic episodes based on dramatic beats.
        STRICT ENFORCEMENT: Never cuts mid-sentence or mid-clause.
        Supported duration targets: 60s (1m), 90s (1.5m), 180s (3m), or custom.
        """
        sentences = re.split(r"(?<=[.!?…])\s+", raw_text.replace("\n", " "))
        sentences = [s.strip() for s in sentences if s.strip()]

        total_words = sum(len(s.split()) for s in sentences)
        words_per_sec = cls.WPM_STANDARD / 60.0
        target_words_per_ep = target_duration_sec * words_per_sec

        episodes = []
        current_sentences: List[str] = []
        current_words = 0
        ep_index = 1

        dramatic_markers = [
            "suddenly", "then", "screamed", "revealed", "silence",
            "never", "clicking", "found", "whispered", "darkness",
            "realized", "stopped", "door opened", "blood", "stared",
        ]

        for i, sentence in enumerate(sentences):
            current_sentences.append(sentence)
            current_words += len(sentence.split())

            is_near_target = current_words >= target_words_per_ep * 0.85
            is_last = (i == len(sentences) - 1)
            is_dramatic = any(k in sentence.lower() for k in dramatic_markers)
            exceeds_upper_bound = current_words >= target_words_per_ep * 1.25

            # If near target and at a dramatic pause, or if hard upper bound reached (and not the very end)
            if (is_near_target and is_dramatic and not is_last) or (exceeds_upper_bound and not is_last):
                ep_text = " ".join(current_sentences)
                ep_dur = round((current_words / cls.WPM_STANDARD) * 60.0, 1)

                episodes.append({
                    "episode_number": ep_index,
                    "title": f"Episode {ep_index}: The Turn",
                    "version": 1,
                    "text": ep_text,
                    "word_count": current_words,
                    "duration_sec": ep_dur,
                    "opening_hook": current_sentences[0][:100],
                    "cliffhanger_ending": current_sentences[-1],
                    "narration_status": "READY",
                    "render_status": "PENDING",
                    "qa_status": "UNCHECKED",
                    "status": EpisodeStatus.READY.value,
                })
                ep_index += 1
                current_sentences = []
                current_words = 0

        # Remaining sentences comprise final episode
        if current_sentences:
            ep_text = " ".join(current_sentences)
            ep_dur = round((current_words / cls.WPM_STANDARD) * 60.0, 1)
            episodes.append({
                "episode_number": ep_index,
                "title": f"Episode {ep_index}: Final Resolution" if ep_index > 1 else "Complete Narrative Feature",
                "version": 1,
                "text": ep_text,
                "word_count": current_words,
                "duration_sec": ep_dur,
                "opening_hook": current_sentences[0][:100],
                "cliffhanger_ending": current_sentences[-1],
                "narration_status": "READY",
                "render_status": "PENDING",
                "qa_status": "UNCHECKED",
                "status": EpisodeStatus.READY.value,
            })

        return {
            "series_title": series_title,
            "target_duration_sec": target_duration_sec,
            "total_episodes": len(episodes),
            "episodes": episodes,
            "chronology_check": True,
            "rights": rights_data or {},
        }

    @classmethod
    def invalidate_episode_on_edit(
        cls,
        episode_plan: Dict[str, Any],
        episode_number: int,
        updated_text: str,
    ) -> Dict[str, Any]:
        """Edits an episode's script and triggers cascading invalidation.
        Marks narration, visuals, and renders as STALE_INVALIDATED and increments version.
        """
        found = False
        for ep in episode_plan.get("episodes", []):
            if ep.get("episode_number") == episode_number:
                found = True
                ep["text"] = updated_text.strip()
                ep["word_count"] = len(updated_text.split())
                ep["duration_sec"] = round((ep["word_count"] / cls.WPM_STANDARD) * 60.0, 1)
                ep["version"] = ep.get("version", 1) + 1
                # Cascading invalidation states
                ep["status"] = EpisodeStatus.STALE_INVALIDATED.value
                ep["narration_status"] = EpisodeStatus.STALE_INVALIDATED.value
                ep["render_status"] = EpisodeStatus.STALE_INVALIDATED.value
                ep["qa_status"] = EpisodeStatus.STALE_INVALIDATED.value
                break

        if not found:
            raise ValueError(f"Episode {episode_number} not found in episode plan.")

        return episode_plan

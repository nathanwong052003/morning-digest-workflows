from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from openai import OpenAI

from config import Settings
from models import DigestSummary, NewsItem, RankedNewsItem
from utils.logging import JsonLogger
from utils.retries import retry_call


SYSTEM_PROMPT = (
    "You are a concise assistant. Return ONLY valid JSON. "
    "Be brief. Prioritize actionable info."
)


class DeepSeekError(Exception):
    pass


class DeepSeekClient:
    def __init__(self, *, settings: Settings, logger: JsonLogger) -> None:
        self.settings = settings
        self.logger = logger
        self.client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        self._daily_tokens = self._read_daily_tokens()
        if settings.deepseek_audit_log_path.strip():
            self._audit_log_path = Path(settings.deepseek_audit_log_path)
        else:
            self._audit_log_path = Path(settings.output_dir) / f"deepseek_requests_{settings.run_id}.jsonl"

    def _token_key(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _read_daily_tokens(self) -> int:
        path = Path(self.settings.token_spend_path)
        if not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        return int(payload.get(self._token_key(), 0))

    def _write_daily_tokens(self) -> None:
        path = Path(self.settings.token_spend_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        else:
            payload = {}
        payload[self._token_key()] = self._daily_tokens
        path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

    def _call_json(self, *, step: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        attempt_number = 0

        def _request() -> Any:
            nonlocal attempt_number
            attempt_number += 1
            request_payload = {
                "model": self.settings.deepseek_model,
                "temperature": self.settings.deepseek_temperature,
                "max_tokens": self.settings.deepseek_max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
                ],
            }
            self.logger.info(
                "deepseek_request",
                step=step,
                attempt=attempt_number,
                model=request_payload["model"],
                temperature=request_payload["temperature"],
                max_tokens=request_payload["max_tokens"],
                user_payload_keys=list(user_payload.keys()),
                user_payload_sizes={
                    k: len(json.dumps(v, ensure_ascii=True))
                    for k, v in user_payload.items()
                },
            )
            self._append_audit_event(
                event="deepseek_request",
                step=step,
                attempt=attempt_number,
                request=request_payload,
            )
            try:
                response = self.client.chat.completions.create(**request_payload)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "deepseek_request_error",
                    step=step,
                    attempt=attempt_number,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                self._append_audit_event(
                    event="deepseek_request_error",
                    step=step,
                    attempt=attempt_number,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                raise
            usage = getattr(response, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
            content = response.choices[0].message.content if response.choices else None
            self.logger.info(
                "deepseek_response",
                step=step,
                attempt=attempt_number,
                response_id=getattr(response, "id", ""),
                model=request_payload["model"],
                finish_reason=(
                    response.choices[0].finish_reason
                    if response.choices and len(response.choices) > 0
                    else ""
                ),
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                tokens_used=total_tokens,
                response_preview=(content[:500] + "..." if content and len(content) > 500 else (content or "")),
            )
            self._append_audit_event(
                event="deepseek_response",
                step=step,
                attempt=attempt_number,
                response_id=getattr(response, "id", ""),
                finish_reason=(
                    response.choices[0].finish_reason
                    if response.choices and len(response.choices) > 0
                    else ""
                ),
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                tokens_used=total_tokens,
                response_content=content or "",
            )
            return response

        try:
            response = retry_call(
                _request,
                attempts=self.settings.ai_retry_attempts,
                base_delay_seconds=1.0,
            )
        except Exception as exc:  # noqa: BLE001
            raise DeepSeekError(f"DeepSeek API request failed at step '{step}'") from exc

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise DeepSeekError(f"DeepSeek returned empty response at step '{step}'")

        try:
            parsed = self._parse_json_payload(content)
        except json.JSONDecodeError as exc:
            self._append_audit_event(
                event="deepseek_response_parse_error",
                step=step,
                response_content=content,
                error=str(exc),
            )
            raise DeepSeekError(f"DeepSeek returned invalid JSON at step '{step}'") from exc
        payload = self._coerce_payload(parsed=parsed, step=step)

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
        self._daily_tokens += total_tokens
        self._write_daily_tokens()
        self.logger.info(
            "ai_call_completed",
            step=step,
            tokens_used=total_tokens,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            latency=perf_counter() - started,
            daily_tokens=self._daily_tokens,
        )
        return payload

    def _append_audit_event(self, *, event: str, step: str, **kwargs: Any) -> None:
        self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "run_id": self.settings.run_id,
            "event": event,
            "step": step,
        }
        payload.update(kwargs)
        with self._audit_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")

    @staticmethod
    def _parse_json_payload(content: str) -> Any:
        text = content.strip()
        candidates: list[str] = [text]

        fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
        if fenced and fenced != text:
            candidates.append(fenced)

        object_start = text.find("{")
        object_end = text.rfind("}")
        if object_start >= 0 and object_end > object_start:
            candidates.append(text[object_start : object_end + 1])

        array_start = text.find("[")
        array_end = text.rfind("]")
        if array_start >= 0 and array_end > array_start:
            candidates.append(text[array_start : array_end + 1])

        last_error: json.JSONDecodeError | None = None
        seen: set[str] = set()
        decoder = json.JSONDecoder()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_error = exc
            for index, char in enumerate(candidate):
                if char not in "{[":
                    continue
                try:
                    parsed, _ = decoder.raw_decode(candidate[index:])
                    return parsed
                except json.JSONDecodeError as exc:
                    last_error = exc
                    continue
        if last_error is not None:
            raise last_error
        raise json.JSONDecodeError("No JSON content found", text, 0)

    @staticmethod
    def _coerce_payload(*, parsed: Any, step: str) -> dict[str, Any]:
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            if step == "ai_rank_news":
                return {"ranked_news": parsed}
            raise DeepSeekError(f"DeepSeek returned list JSON at step '{step}', expected object")
        raise DeepSeekError(f"DeepSeek returned unsupported JSON type at step '{step}'")

    @staticmethod
    def _normalize_url_for_match(raw_url: str) -> str:
        stripped = raw_url.strip()
        if not stripped:
            return ""
        parts = urlsplit(stripped)
        path = parts.path.rstrip("/") or "/"
        normalized = parts._replace(
            scheme=parts.scheme.lower(),
            netloc=parts.netloc.lower(),
            path=path,
            fragment="",
        )
        return urlunsplit(normalized)

    def is_budget_exceeded(self) -> bool:
        exceeded = self._daily_tokens > self.settings.daily_token_warn_threshold
        if exceeded:
            print(
                f"WARNING: daily token usage {self._daily_tokens} "
                f"exceeds threshold {self.settings.daily_token_warn_threshold}"
            )
            self.logger.warning(
                "token_budget_exceeded",
                step="ai",
                daily_tokens=self._daily_tokens,
                threshold=self.settings.daily_token_warn_threshold,
            )
        return exceeded

    def rank_news(
        self,
        news_items: list[NewsItem],
        *,
        category: str = "TECHNOLOGY",
    ) -> list[RankedNewsItem]:
        """Rank news items for a specific category.

        The category is pre-determined (from RSS feed grouping), so the AI only
        needs to rank relevance and assign a tag + summary — no category guessing needed.
        """
        if not news_items:
            return []

        category_lower = category.lower().replace(" ", "_")
        tags_by_category = {
            "TECHNOLOGY": "AI, Hardware, Software, Cybersecurity, Science, Robotics, Space",
            "SOUTHEAST ASIA": "Finance, Policy, Startups, Society, Security, Trade, Energy, Environment",
            "HONG KONG": "Finance, Society, Policy, Business, Security, Culture, Education",
        }
        tags = tags_by_category.get(category, "News")
        summary_length = (
            "3-4 detailed complete sentences providing substantive context and detail"
            if category in ("SOUTHEAST ASIA", "HONG KONG")
            else "2-3 detailed complete sentences providing substantive information"
        )

        indexed_news = list(enumerate(news_items))
        payload = {
            "task": (
                f"Rank each {category_lower} news item for today's relevance. "
                "Return JSON with key 'ranked_news' containing list of "
                "{item_id,title,url,relevance,reason,tag,summary}. "
                "Use the exact item_id provided in input. relevance is integer 0-100. "
                f"Tags for this category: {tags}. "
                f"summary must be {summary_length}. "
                "Never end mid-sentence. Do not include ellipsis. "
                "Do NOT mention the news source or publication name in the summary text."
            ),
            "news": [
                {
                    "item_id": f"news_{idx}",
                    **item.model_dump(mode="json"),
                }
                for idx, item in indexed_news[:30]
            ],
        }
        result = self._call_json(step=f"ai_rank_{category_lower}", user_payload=payload)
        ranked_raw = result.get("ranked_news", [])
        if not isinstance(ranked_raw, list):
            ranked_raw = []
        if not ranked_raw:
            fallback_rows = result.get("items")
            if isinstance(fallback_rows, list):
                ranked_raw = fallback_rows
        if not ranked_raw:
            fallback_rows = result.get("news")
            if isinstance(fallback_rows, list):
                ranked_raw = fallback_rows
        by_item_id = {f"news_{idx}": idx for idx, _ in indexed_news}
        by_url = {str(item.url): idx for idx, item in indexed_news}
        by_url_normalized = {
            self._normalize_url_for_match(str(item.url)): idx for idx, item in indexed_news
        }
        by_title = {item.title.strip().casefold(): idx for idx, item in indexed_news if item.title.strip()}

        scores: dict[int, tuple[int, str, str, str]] = {}
        for row in ranked_raw:
            if not isinstance(row, dict):
                continue
            item_index: int | None = None
            row_item_id = str(row.get("item_id", "")).strip()
            if row_item_id and row_item_id in by_item_id:
                item_index = by_item_id[row_item_id]
            else:
                row_url = str(row.get("url", "")).strip()
                item_index = by_url.get(row_url)
                if item_index is None:
                    item_index = by_url_normalized.get(self._normalize_url_for_match(row_url))
                if item_index is None:
                    row_title = str(row.get("title", "")).strip().casefold()
                    if row_title:
                        item_index = by_title.get(row_title)
            if item_index is None:
                continue
            relevance = row.get("relevance", 50)
            try:
                score = int(relevance)
            except (TypeError, ValueError):
                score = 50
            score = min(100, max(0, score))
            scores[item_index] = (
                score,
                str(row.get("reason", "")),
                str(row.get("tag", "")).strip(),
                str(row.get("summary", "")).strip(),
            )

        ranked_items = []
        for idx, item in indexed_news:
            score, reason, tag, ai_summary = scores.get(
                idx,
                (50, "Default relevance due to parsing fallback.", "", ""),
            )
            ranked_items.append(
                RankedNewsItem(
                    title=item.title,
                    url=item.url,
                    source=item.source,
                    published_at=item.published_at,
                    snippet=item.snippet,
                    relevance=score,
                    reason=reason,
                    category=category,
                    tag=tag,
                    ai_summary=ai_summary,
                )
            )
        ranked_items.sort(key=lambda item: item.relevance, reverse=True)
        return ranked_items

    def refine_news_summaries(self, ranked_news: list[RankedNewsItem]) -> list[RankedNewsItem]:
        if not ranked_news:
            return ranked_news
        payload = {
            "task": (
                "Rewrite each item into a detailed summary using title/source/snippet context. "
                "Return JSON object with key 'summaries' containing list of {item_id,summary}. "
                "For SOUTHEAST ASIA and HONG KONG items, write longer 3-4 sentence summaries with more context and detail. "
                "For TECHNOLOGY items, write 2-3 sentence summaries. "
                "Summary must be complete sentences, not ending mid-sentence, and must not include ellipsis. "
                "Do NOT mention the news source or publication name in the summary text."
            ),
            "items": [
                {
                    "item_id": f"news_{idx}",
                    "title": item.title,
                    "source": item.source,
                    "url": str(item.url),
                    "snippet": item.snippet,
                    "current_summary": item.ai_summary,
                }
                for idx, item in enumerate(ranked_news[:24])
            ],
        }
        result = self._call_json(step="ai_refine_news_summaries", user_payload=payload)
        summary_rows = result.get("summaries", [])
        if not isinstance(summary_rows, list):
            summary_rows = []

        summary_map: dict[int, str] = {}
        for row in summary_rows:
            if not isinstance(row, dict):
                continue
            raw_item_id = str(row.get("item_id", "")).strip()
            raw_summary = str(row.get("summary", "")).strip()
            if not raw_item_id.startswith("news_") or not raw_summary:
                continue
            try:
                item_index = int(raw_item_id.split("_", 1)[1])
            except (TypeError, ValueError):
                continue
            summary_map[item_index] = raw_summary

        for idx, item in enumerate(ranked_news):
            replacement = summary_map.get(idx, "").strip()
            if replacement:
                item.ai_summary = replacement
        return ranked_news

    def summarize(
        self,
        *,
        ranked_news: list[RankedNewsItem],
    ) -> DigestSummary:
        payload = {
            "task": (
                "Create compact summary for news only. Return JSON with keys exactly: "
                "news, action_items. Each key must hold an array of short strings."
            ),
            "news": [item.model_dump(mode="json") for item in ranked_news[:12]],
        }
        result = self._call_json(step="ai_summarize", user_payload=payload)
        try:
            summary = DigestSummary(
                schedule=[],
                emails=[],
                news=[str(item) for item in result.get("news", [])],
                action_items=[str(item) for item in result.get("action_items", [])],
            )
        except Exception as exc:  # noqa: BLE001
            raise DeepSeekError("Failed to normalize DeepSeek summary output.") from exc
        return summary

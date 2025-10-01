from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass
class DispatchMessage:
    payload: str
    topic: Optional[str] = None
    routing_key: Optional[str] = None
    exchange: Optional[str] = None
    qos: Optional[int] = None
    retain: Optional[bool] = None
    url: Optional[str] = None
    method: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    persistent: Optional[bool] = None
    content_type: Optional[str] = None


@dataclass
class RouteContext:
    value: Any
    root: Any
    index: Optional[int] = None
    key: Optional[Any] = None
    path: Optional[str] = None


class RouteRule:
    _INDEX_PATTERN = re.compile(r"\{(\d+)\}")
    _NAME_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

    def __init__(self, config: Dict[str, Any]) -> None:
        when_cfg = config.get("when") or {}
        if not isinstance(when_cfg, dict):
            raise ValueError("Route 'when' section must be a dictionary")

        publish_cfg = config.get("publish") or {}
        if not isinstance(publish_cfg, dict):
            raise ValueError("Route 'publish' section must be a dictionary")

        self._when_type = str(when_cfg.get("type", "all")).lower()
        self._path = when_cfg.get("path")
        self._foreach = _to_bool(when_cfg.get("foreach", False))

        self._publish_cfg = publish_cfg

    def dispatch(self, root: Any) -> List[DispatchMessage]:
        contexts = list(self._resolve_contexts(root))
        messages: List[DispatchMessage] = []
        for context in contexts:
            message = self._build_message(context)
            if message is not None:
                messages.append(message)
        return messages

    def _resolve_contexts(self, root: Any) -> Iterable[RouteContext]:
        if self._when_type == "all":
            yield RouteContext(value=root, root=root, path=self._path)
            return

        if self._when_type == "json_path" and isinstance(self._path, str):
            value = _extract_json_path(root, self._path)
            if value is _MISSING:
                return
            if self._foreach:
                if isinstance(value, dict):
                    for idx, (key, item) in enumerate(value.items()):
                        yield RouteContext(
                            value=item,
                            root=root,
                            index=idx,
                            key=key,
                            path=f"{self._path}.{key}",
                        )
                elif isinstance(value, (list, tuple)):
                    for idx, item in enumerate(value):
                        yield RouteContext(
                            value=item,
                            root=root,
                            index=idx,
                            path=f"{self._path}[{idx}]",
                        )
                else:
                    yield RouteContext(value=value, root=root, index=0, path=self._path)
            else:
                yield RouteContext(value=value, root=root, path=self._path)
        elif self._when_type == "json_path":
            return

    def _build_message(self, context: RouteContext) -> Optional[DispatchMessage]:
        publish_cfg = self._publish_cfg
        payload_template = publish_cfg.get("payload")
        topic_template = publish_cfg.get("topic")
        routing_key_template = publish_cfg.get("routing_key")
        exchange_template = publish_cfg.get("exchange")
        url_template = publish_cfg.get("url")
        method_template = publish_cfg.get("method")
        qos_template = publish_cfg.get("qos")
        retain_template = publish_cfg.get("retain")
        headers_template = publish_cfg.get("headers")
        persistent_template = publish_cfg.get("persistent")
        content_type_template = publish_cfg.get("content_type")

        payload_value = (
            self._render_value(payload_template, context)
            if payload_template is not None
            else _default_payload(context.value)
        )
        payload_str = (
            payload_value
            if isinstance(payload_value, str)
            else json.dumps(payload_value, ensure_ascii=False)
        )

        message = DispatchMessage(payload=payload_str)
        message.topic = _optional_str(self._render_value(topic_template, context))
        message.routing_key = _optional_str(
            self._render_value(routing_key_template, context)
        )
        message.exchange = _optional_str(
            self._render_value(exchange_template, context)
        )
        message.url = _optional_str(self._render_value(url_template, context))
        method_rendered = self._render_value(method_template, context)
        if isinstance(method_rendered, str) and method_rendered:
            message.method = method_rendered.upper()

        qos_rendered = self._render_value(qos_template, context)
        if qos_rendered is not None:
            try:
                message.qos = int(qos_rendered)
            except (TypeError, ValueError):
                message.qos = None

        retain_rendered = self._render_value(retain_template, context)
        if retain_rendered is not None:
            message.retain = _to_bool(retain_rendered)

        persistent_rendered = self._render_value(persistent_template, context)
        if persistent_rendered is not None:
            message.persistent = _to_bool(persistent_rendered)

        headers_rendered = self._render_headers(headers_template, context)
        if headers_rendered:
            message.headers = headers_rendered

        content_type_rendered = self._render_value(content_type_template, context)
        if isinstance(content_type_rendered, str) and content_type_rendered:
            message.content_type = content_type_rendered

        return message

    def _render_headers(
        self, headers_template: Any, context: RouteContext
    ) -> Optional[Dict[str, str]]:
        if headers_template is None:
            return None
        if isinstance(headers_template, dict):
            rendered: Dict[str, str] = {}
            for key, value in headers_template.items():
                rendered_key = str(key)
                rendered_value = self._render_value(value, context)
                if rendered_value is None:
                    continue
                rendered[rendered_key] = str(rendered_value)
            return rendered
        value = self._render_value(headers_template, context)
        if value is None:
            return None
        return {"value": str(value)}

    def _render_value(self, template: Any, context: RouteContext) -> Any:
        if template is None:
            return None
        if isinstance(template, str):
            return self._render_string(template, context)
        if isinstance(template, list):
            return [self._render_value(item, context) for item in template]
        if isinstance(template, dict):
            return {key: self._render_value(val, context) for key, val in template.items()}
        return template

    def _render_string(self, template: str, context: RouteContext) -> str:
        tokens = self._build_tokens(context)
        positional = _build_positional(context.value)
        result = template
        if positional:
            result = self._INDEX_PATTERN.sub(
                lambda match: _stringify(
                    positional[int(match.group(1))]
                    if int(match.group(1)) < len(positional)
                    else ""
                ),
                result,
            )
        result = self._NAME_PATTERN.sub(
            lambda match: tokens.get(match.group(1), match.group(0)),
            result,
        )
        return result

    def _build_tokens(self, context: RouteContext) -> Dict[str, str]:
        tokens: Dict[str, str] = {
            "raw": json.dumps(context.value, ensure_ascii=False),
            "value": _stringify(context.value),
            "path": context.path or "",
        }
        if context.index is not None:
            tokens["index"] = str(context.index)
        if context.key is not None:
            tokens["key"] = _stringify(context.key)
        tokens["root"] = json.dumps(context.root, ensure_ascii=False)
        return tokens


class ResultRouter:
    def __init__(self, routes_config: Optional[Sequence[Dict[str, Any]]]) -> None:
        self._routes: List[RouteRule] = []
        if routes_config:
            for item in routes_config:
                if not isinstance(item, dict):
                    raise ValueError("Each route must be a dictionary")
                self._routes.append(RouteRule(item))

    def dispatch(self, data: Any) -> List[DispatchMessage]:
        if not self._routes:
            return []
        messages: List[DispatchMessage] = []
        for route in self._routes:
            messages.extend(route.dispatch(data))
        return messages

    @property
    def has_routes(self) -> bool:
        return bool(self._routes)


class _Missing:
    pass


_MISSING = _Missing()


def normalise_routes_config(value: Any) -> Optional[List[Dict[str, Any]]]:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        routes_value = value.get("routes")
        if isinstance(routes_value, list):
            return routes_value
    raise ValueError("Routes configuration must be a list of dictionaries")


def _extract_json_path(root: Any, path: str) -> Any:
    current = root
    for part in path.split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return _MISSING
    return current


def _build_positional(value: Any) -> List[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return []
    return [value]


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    return str(value)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "on", "1"}:
            return True
        if lowered in {"false", "no", "off", "0"}:
            return False
    return bool(value)


def _default_payload(value: Any) -> Any:
    if isinstance(value, (str, bytes)):
        return value
    return value

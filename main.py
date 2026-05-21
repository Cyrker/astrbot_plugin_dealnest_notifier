import asyncio
from contextlib import suppress
from typing import Any

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star


class DealNestNotifier(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._poll_task: asyncio.Task[None] | None = asyncio.create_task(self._poll_loop())

    def _get_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _get_int(self, key: str, default: int) -> int:
        try:
            return max(1, int(self.config.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _get_str(self, key: str) -> str:
        return str(self.config.get(key, "") or "").strip()

    def _base_url(self) -> str:
        return self._get_str("dealnest_base_url").rstrip("/")

    def _normalize_targets(self, value: Any) -> list[str]:
        if isinstance(value, str):
            raw_targets = value.replace(",", "\n").splitlines()
        elif isinstance(value, (list, tuple, set)):
            raw_targets = value
        else:
            raw_targets = []

        targets: list[str] = []
        seen: set[str] = set()
        for raw_target in raw_targets:
            target = str(raw_target or "").strip()
            if target and target not in seen:
                targets.append(target)
                seen.add(target)
        return targets

    def _target_umos(self) -> list[str]:
        targets = self._normalize_targets(self.config.get("target_umos", ""))
        legacy_target = self._get_str("target_umo")
        if legacy_target and legacy_target not in targets:
            targets.append(legacy_target)
        return targets

    def _save_target_umos(self, targets: list[str]) -> None:
        normalized = self._normalize_targets(targets)
        self.config["target_umos"] = "\n".join(normalized)
        self.config["target_umo"] = ""
        self.config.save_config()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_str('token')}"}

    async def _request_json(
        self,
        session: aiohttp.ClientSession,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url()}{path}"
        async with session.request(method, url, headers=self._headers(), json=json_body) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"DealNest API 返回 {response.status}: {text[:200]}")
            if not text:
                return {}
            return await response.json(content_type=None)

    async def _ack(
        self,
        session: aiohttp.ClientSession,
        notification: dict[str, Any],
        status: str,
        error_message: str | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "leaseToken": notification["leaseToken"],
            "status": status,
        }
        if error_message:
            body["errorMessage"] = error_message[:1000]

        last_error: Exception | None = None
        for _ in range(2):
            try:
                await self._request_json(
                    session,
                    "POST",
                    f"/api/bot-notifications/{notification['id']}/ack",
                    json_body=body,
                )
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(1)
        if last_error:
            raise last_error

    def _notification_targets(self, notification: dict[str, Any]) -> list[str]:
        explicit_target = str(notification.get("target") or "").strip()
        return [explicit_target] if explicit_target else self._target_umos()

    async def _send_notification(self, notification: dict[str, Any]) -> None:
        targets = self._notification_targets(notification)
        if not targets:
            raise RuntimeError("未绑定通知群，无法发送群通知")

        text = str(notification.get("message") or notification.get("title") or "").strip()
        if not text:
            raise RuntimeError("通知内容为空")

        sent_count = 0
        failures: list[str] = []
        for target in targets:
            try:
                sent = await self.context.send_message(target, MessageChain().message(text))
                if sent is False:
                    raise RuntimeError("AstrBot 未找到目标会话")
                sent_count += 1
            except Exception as exc:
                failures.append(f"{target}: {exc}")

        if failures:
            logger.warning(
                f"DealNest QQBOT 群通知部分发送失败: 成功 {sent_count} 个，失败 {len(failures)} 个；"
                f"{'; '.join(failures[:3])}"
            )
        if sent_count == 0:
            raise RuntimeError(f"所有通知群发送失败: {'; '.join(failures[:3])}")

    async def _poll_once(self) -> tuple[int, int]:
        idle_interval = self._get_int("poll_interval_seconds", 30)
        failure_backoff = self._get_int("failure_backoff_seconds", 60)
        if not self._get_bool("enabled", True):
            return 0, idle_interval
        if not self._base_url() or not self._get_str("token"):
            return 0, idle_interval

        timeout = aiohttp.ClientTimeout(total=self._get_int("request_timeout_seconds", 15))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                limit = self._get_int("batch_size", 10)
                data = await self._request_json(session, "GET", f"/api/bot-notifications/pending?limit={limit}")
                items = data.get("items") if isinstance(data, dict) else []
                if not isinstance(items, list):
                    return 0, idle_interval

                delivered = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    try:
                        await self._send_notification(item)
                    except Exception as exc:
                        logger.warning(f"DealNest QQBOT 通知发送失败: {exc}")
                        with suppress(Exception):
                            await self._ack(session, item, "FAILED", str(exc))
                        continue

                    await self._ack(session, item, "SENT")
                    delivered += 1

                next_poll = data.get("nextPollAfterSeconds", idle_interval) if isinstance(data, dict) else idle_interval
                return delivered, max(1, int(next_poll))
        except Exception as exc:
            logger.warning(f"DealNest QQBOT 通知拉取失败: {exc}")
            return 0, failure_backoff

    async def _poll_loop(self) -> None:
        while True:
            _, next_wait = await self._poll_once()
            await asyncio.sleep(next_wait)

    @filter.command("dn_bind_group")
    async def bind_group(self, event: AstrMessageEvent):
        """把当前 QQ 群绑定为 DealNest 通知群。"""
        group_id = str(getattr(event.message_obj, "group_id", "") or "").strip()
        if not group_id:
            yield event.plain_result("请在需要接收通知的 QQ 群里执行这个命令。")
            return

        targets = self._target_umos()
        current_target = str(event.unified_msg_origin or "").strip()
        if current_target in targets:
            yield event.plain_result(f"当前群已在 DealNest 通知群列表中，共 {len(targets)} 个群。")
            return

        targets.append(current_target)
        self._save_target_umos(targets)
        yield event.plain_result(f"已绑定当前群为 DealNest 通知群，共 {len(targets)} 个群。")

    @filter.command("dn_unbind_group")
    async def unbind_group(self, event: AstrMessageEvent):
        """从 DealNest 通知群列表移除当前 QQ 群。"""
        group_id = str(getattr(event.message_obj, "group_id", "") or "").strip()
        if not group_id:
            yield event.plain_result("请在需要移除通知绑定的 QQ 群里执行这个命令。")
            return

        current_target = str(event.unified_msg_origin or "").strip()
        targets = self._target_umos()
        next_targets = [target for target in targets if target != current_target]
        if len(next_targets) == len(targets):
            yield event.plain_result(f"当前群未绑定为 DealNest 通知群，共 {len(targets)} 个群。")
            return

        self._save_target_umos(next_targets)
        yield event.plain_result(f"已移除当前通知群，剩余 {len(next_targets)} 个群。")

    @filter.command("dn_notify_status")
    async def notify_status(self, event: AstrMessageEvent):
        """查看 DealNest 通知插件状态。"""
        enabled = self._get_bool("enabled", True)
        has_base_url = bool(self._base_url())
        has_token = bool(self._get_str("token"))
        target_count = len(self._target_umos())
        yield event.plain_result(
            "\n".join(
                [
                    f"enabled: {enabled}",
                    f"dealnest_base_url: {'已配置' if has_base_url else '未配置'}",
                    f"token: {'已配置' if has_token else '未配置'}",
                    f"target_groups: {target_count}",
                ]
            )
        )

    @filter.command("dn_poll_now")
    async def poll_now(self, event: AstrMessageEvent):
        """立即拉取一次 DealNest 待发送通知。"""
        delivered, next_wait = await self._poll_once()
        yield event.plain_result(f"本次发送 {delivered} 条，下一次建议等待 {next_wait} 秒。")

    async def terminate(self):
        if self._poll_task:
            self._poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._poll_task

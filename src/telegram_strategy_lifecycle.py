"""Trusted Telegram bridge; uploaded JSON is data, never executable code."""
from concurrent.futures import CancelledError, Future, TimeoutError as FutureTimeoutError
import json
from pathlib import Path
import queue
import secrets
import threading
import time

from .multi_strategy_lifecycle import Lifecycle, TERMINAL
from .strategy_dashboard import journal_metrics, sandbox_counts
from .strategy_packages import PackageStore, canonical, parse, sha
from .telegram_buttons import TelegramResponse


COMMANDS = {"/dashboard", "/strategies", "/strategy_approve", "/strategy_reject", "/strategy_run",
            "/strategy_status", "/strategy_dashboard", "/strategy_stop", "/strategy_report"}
HELP = ("JSON package: send a .json document (max 128 KiB).\n"
        "/dashboard\n/strategies [page]\n/strategy_approve ID VERSION\n/strategy_reject ID VERSION\n"
        "/strategy_run ID VERSION\n/strategy_status ID VERSION\n"
        "/strategy_dashboard ID VERSION\n"
        "/strategy_stop ID VERSION\n/strategy_report ID VERSION\n"
        "Approval and queue/start are separate explicit actions. Paper only.")


class StrategyService:
    def __init__(self, root, runtime_factory=None, max_concurrent_strategies=2, stop_event=None, stopped_startup=False):
        self.stopped_startup = stopped_startup
        self.root = Path(root).resolve()
        self.jobs = queue.Queue(maxsize=32)
        self.stopping = threading.Event()
        self.external_stop = stop_event if stop_event is not None else threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.tick_error = None
        self.ui_confirmations = {}
        self.thread = threading.Thread(target=self._serve, args=(runtime_factory, max_concurrent_strategies),
                                       name="package-control", daemon=False)
        self.thread.start()
        if not self.ready.wait(10):
            self.stopping.set()
            raise RuntimeError("package service initialization pending shutdown")
        if self.error:
            raise RuntimeError("package service unavailable: " + self.error)

    def _serve(self, factory, limit):
        store = lifecycle = None
        try:
            store = PackageStore(self.root / "packages.sqlite3")
            lifecycle = Lifecycle(self.root / "runtime", store.path, limit, factory,
                                  stopped_startup=self.stopped_startup)
            self.ready.set()
            while not self.stopping.is_set() and not self.external_stop.is_set():
                try:
                    action, value, future = self.jobs.get(timeout=0.1)
                except queue.Empty:
                    pass
                else:
                    if self.stopping.is_set() or self.external_stop.is_set():
                        future.cancel()
                        break
                    if future.set_running_or_notify_cancel():
                        try:
                            if action == "ui":
                                result = self._ui(store, lifecycle, *value)
                            else:
                                result = self._upload(store, value) if action == "upload" else self._command(store, lifecycle, value)
                        except Exception as exc:
                            result = TelegramResponse("Package action not completed: " + type(exc).__name__ +
                                                      ". Check package/status; no execution permission bypass.")
                            if action == "ui":
                                result = TelegramResponse("Действие не завершено: " + type(exc).__name__ +
                                                          ". Обновите карточку и проверьте состояние.", self._ui_home())
                        future.set_result(result)
                if self.stopping.is_set() or self.external_stop.is_set():
                    break
                try:
                    lifecycle.tick()
                    self.tick_error = None
                except Exception as exc:
                    self.tick_error = type(exc).__name__
        except Exception as exc:
            self.error = type(exc).__name__
        finally:
            self.ready.set()
            if lifecycle is not None:
                while True:
                    try:
                        lifecycle.close(timeout=1)
                        break
                    except TimeoutError:
                        self.tick_error = "workers_finalizing"
            if store is not None:
                store.close()
            while not self.jobs.empty():
                _, _, future = self.jobs.get_nowait()
                future.cancel()

    def _request(self, action, value):
        if self.error or self.stopping.is_set() or self.external_stop.is_set() or not self.thread.is_alive():
            return TelegramResponse("Package service unavailable; no action accepted.")
        future = Future()
        try:
            self.jobs.put_nowait((action, value, future))
        except queue.Full:
            return TelegramResponse("Package service busy; no action accepted.")
        try:
            return future.result(timeout=3)
        except CancelledError:
            return TelegramResponse("Request cancelled during shutdown; not executed.")
        except FutureTimeoutError:
            cancelled = future.cancel()
            return TelegramResponse("Request cancelled before execution." if cancelled else
                                    "Request still processing. Check /strategy_status; completion is not confirmed.")

    def upload(self, raw):
        return self._request("upload", raw)

    def command(self, text):
        return self._request("command", text)

    def ui(self, data, user_id, chat_id, raw=None):
        response = self._request("ui", (data, (str(user_id), str(chat_id)), raw))
        if response.reply_markup is None and not response.documents:
            return TelegramResponse("Сервис занят или недоступен. Выполнение не подтверждено. "
                                    "Обновите состояние перед повторным действием.", self._ui_home())
        return response

    @staticmethod
    def _ui_button(text, data):
        return {"text": text, "callback_data": "ui:" + data}

    @classmethod
    def _ui_home(cls):
        b = cls._ui_button
        return {"inline_keyboard": [
            [b("Dashboard", "dashboard"), b("Добавить стратегию", "add")],
            [b("Активные", "active:1"), b("Все стратегии", "all:1")],
            [b("Отчёты", "reports:1"), b("Состояние системы", "system")],
        ]}

    @staticmethod
    def _ui_key(package):
        package = package.get("package", package)
        return sha(canonical([package["strategy_id"], package["version"]]))[:24]

    @staticmethod
    def _ui_state(value):
        return {"uploaded": "загружена", "validated": "проверена", "approved": "одобрена",
                "rejected": "отклонена", "queued": "в очереди", "running": "работает",
                "paused": "пауза", "stopped": "остановлена", "finished": "завершена",
                "expired": "срок истёк", "failed": "ошибка", "not_started": "не запущена",
                "completed": "завершена"}.get(value, value)

    @staticmethod
    def _ui_stamp(package, row):
        return (package["status"], package["package_sha256"],
                tuple((row or {}).get(k) for k in
                      ("session_id", "state", "requested", "startup_held", "recovery_pending")))

    def _ui(self, store, lifecycle, data, actor, raw):
        """Presentation only, serialized with existing commands on the service thread."""
        b = self._ui_button
        back = [b("Главный экран", "home")]
        now = time.monotonic()
        self.ui_confirmations = {k: v for k, v in self.ui_confirmations.items() if v[0] > now}
        if data == "ui:upload":
            self._upload(store, raw)
            package = parse(raw)
            saved = store.get(package["strategy_id"], package["version"])
            if saved["package_sha256"] != sha(canonical(package)):
                return TelegramResponse("Эта версия уже загружена с другим содержимым. Используйте новую версию.", self._ui_home())
            card = self._ui_card(saved, lifecycle)
            note = ("Файл принят. Стратегия не запущена.\n" if saved["status"] != "uploaded" else
                    "Файл сохранён, но проверка не пройдена. Исправьте контракт и загрузите новую версию.\n")
            return TelegramResponse(note + card.text, card.reply_markup)
        if data in {"ui:home", "ui:cancel"}:
            self.ui_confirmations = {k: v for k, v in self.ui_confirmations.items() if v[1] != actor}
            return TelegramResponse("sandbox-13 • Главное меню\nМодельные сделки. Выберите действие.", self._ui_home())
        if data == "ui:add":
            return TelegramResponse("Отправьте в этот чат файл стратегии .json как документ (до 128 КиБ).\n"
                                    "После проверки появится карточка. Одобрение и запуск подтверждаются отдельно.",
                                    {"inline_keyboard": [back]})
        packages = store.list_packages()
        rows = lifecycle.status()
        sessions = {(r["strategy_id"], r["version"]): r for r in rows}
        if data in {"ui:dashboard", "ui:system"}:
            counts = sandbox_counts(packages, rows)
            if data == "ui:dashboard":
                text = ("sandbox-13 • Dashboard\n"
                        f"Работают: {counts['running']} • В очереди: {counts['queued']}\n"
                        f"Завершены: {counts['finished']} • Отклонены: {counts['rejected']} • Ожидают: {counts['idle']}\n"
                        "Доходность смотрите в карточках отдельных версий. Исторические результаты не суммируются с текущими.")
            else:
                text = ("Состояние системы • sandbox-13\nКонтроллер отвечает. Режим: модельные сделки.\n"
                        f"Рабочих потоков: {sum(bool(r['worker_alive']) for r in rows)}\n"
                        f"Ожидают ручного запуска после перезапуска: {sum(bool(r.get('startup_held')) for r in rows)}\n"
                        f"Ожидают восстановления: {sum(bool(r.get('recovery_pending')) for r in rows)}\n"
                        f"Проблем хранения: {sum(bool(r.get('persistence_blocker')) for r in rows)}\n"
                        f"Планировщик: {self.tick_error or 'без зарегистрированных ошибок'}\n"
                        "Это состояние контроллера; доступность рыночных данных указана в карточках.")
            return TelegramResponse(text, self._ui_home())
        parts = data.split(":")
        if len(parts) == 3 and parts[1] in {"all", "active", "reports"}:
            mode = parts[1]
            selected = []
            for package in packages:
                row = sessions.get((package["package"]["strategy_id"], package["package"]["version"]))
                if mode == "active" and (not row or row["state"] in TERMINAL):
                    continue
                if mode == "reports" and (not row or row["state"] not in TERMINAL or not row["report"]):
                    continue
                selected.append(package)
            last = max(1, (len(selected) + 4) // 5)
            page = min(last, max(1, int(parts[2])))
            keyboard = [[b(f"{p['package']['strategy_id']}/{p['package']['version']}", "card:" + self._ui_key(p))]
                        for p in selected[(page - 1) * 5:page * 5]]
            nav = []
            if page > 1:
                nav.append(b("← Назад", f"{mode}:{page - 1}"))
            if page < last:
                nav.append(b("Далее →", f"{mode}:{page + 1}"))
            if nav:
                keyboard.append(nav)
            keyboard.append(back)
            title = {"all": "Все стратегии", "active": "Активные стратегии", "reports": "Готовые отчёты"}[mode]
            return TelegramResponse(f"{title} • {len(selected)}\nСтраница {page}/{last}\n" +
                                    ("Выберите стратегию." if selected else "Пока пусто."), {"inline_keyboard": keyboard})
        if len(parts) == 3 and parts[1] == "confirm":
            pending = self.ui_confirmations.get(parts[2])
            if pending is None or pending[1] != actor:
                return TelegramResponse("Подтверждение недействительно или устарело. Откройте карточку заново.", self._ui_home())
            del self.ui_confirmations[parts[2]]  # Single use even if command fails.
            _, _, action, sid, version, stamp = pending
            package = store.get(sid, version)
            row = sessions.get((sid, version))
            if stamp != self._ui_stamp(package, row):
                return TelegramResponse("Состояние изменилось. Проверьте карточку и подтвердите действие заново.", self._ui_card(package, lifecycle).reply_markup)
            self._command(store, lifecycle, f"/strategy_{action} {sid} {version}")
            card = self._ui_card(store.get(sid, version), lifecycle)
            note = {"approve": "Одобрение обработано; запуск — отдельное действие.",
                    "reject": "Отклонение обработано.",
                    "run": "Запрос на запуск принят. Фактическое состояние указано ниже.",
                    "stop": "Запрос на остановку принят. Дождитесь остановки рабочего потока."}[action]
            return TelegramResponse(note + "\n" + card.text, card.reply_markup)
        if len(parts) not in {3, 4} or parts[1] not in {"card", "details", "report", "ask"}:
            return TelegramResponse("Кнопка устарела. Откройте главное меню.", self._ui_home())
        key = parts[-1]
        matches = [p for p in packages if self._ui_key(p) == key]
        if len(matches) != 1:
            return TelegramResponse("Стратегия не найдена. Обновите список.", self._ui_home())
        package = matches[0]
        sid, version = package["package"]["strategy_id"], package["package"]["version"]
        row = sessions.get((sid, version))
        if parts[1] in {"card", "details"}:
            return self._ui_card(package, lifecycle, details=parts[1] == "details")
        if parts[1] == "report":
            result = self._command(store, lifecycle, f"/strategy_report {sid} {version}")
            return TelegramResponse("Отчёт готов к отправке." if result.documents else
                                    "Отчёт ещё не готов или недоступен. Проверьте состояние стратегии.",
                                    self._ui_card(package, lifecycle).reply_markup, result.documents)
        if len(parts) != 4 or parts[2] not in self._ui_actions(package, row):
            return TelegramResponse("Действие недоступно в текущем состоянии.", self._ui_card(package, lifecycle).reply_markup)
        action = parts[2]
        # A new question supersedes this actor's earlier question.
        self.ui_confirmations = {k: v for k, v in self.ui_confirmations.items() if v[1] != actor}
        token = secrets.token_urlsafe(16)
        self.ui_confirmations[token] = (now + 120, actor, action, sid, version, self._ui_stamp(package, row))
        label = self._ui_actions(package, row)[action]
        return TelegramResponse(f"{label}: {sid}/{version}?\nПодтверждение действует 2 минуты.\n" +
                                ("Одобрение само по себе не запускает стратегию." if action == "approve" else
                                 "Действие относится только к этой версии стратегии."),
                                {"inline_keyboard": [[b("Подтвердить: " + label.lower(), "confirm:" + token)],
                                                     [b("Отмена", "cancel")]]})

    @staticmethod
    def _ui_actions(package, row):
        actions = {}
        if package["status"] == "validated":
            actions["approve"] = "Одобрить"
        if package["status"] in {"uploaded", "validated"}:
            actions["reject"] = "Отклонить"
        if package["status"] == "approved" and (row is None or
                (row["state"] not in TERMINAL and (row.get("startup_held") or row["state"] == "paused"))):
            actions["run"] = "Запустить"
        if row and row["state"] not in TERMINAL:
            actions["stop"] = "Остановить"
        return actions

    def _ui_card(self, package, lifecycle, details=False):
        sid, version = package["package"]["strategy_id"], package["package"]["version"]
        row = next((r for r in lifecycle.status() if (r["strategy_id"], r["version"]) == (sid, version)), None)
        key = self._ui_key(package)
        b = self._ui_button
        keyboard = [[b("Подробнее", "details:" + key), b("Отчёт", "report:" + key)]]
        for action, label in self._ui_actions(package, row).items():
            keyboard.append([b(label, f"ask:{action}:{key}")])
        keyboard += [[b("Обновить", "card:" + key), b("Все стратегии", "all:1")], [b("Главный экран", "home")]]
        data = journal_metrics(lifecycle.root / "sessions" / row["session_id"], row, package["package"]) if row else {}
        def value(name, suffix=""):
            item = data.get(name)
            if item is None:
                return "н/д"
            return str(item) + suffix
        pf = "∞ (нет убыточных закрытий)" if data.get("profit_factor_reason") == "no realized losses" else value("profit_factor")
        gaps = data.get("data_gaps", {})
        gap_text = (f"недоступно символов: {len(gaps.get('unavailable_symbols', {}))}; "
                    f"позиций с пропусками: {gaps.get('gap_exposed_positions', 0)}") if gaps.get("available") else "н/д (нет журнала)"
        text = (f"{sid}/{version}\nПакет: {self._ui_state(package['status'])} • Статус: {self._ui_state(row['state'] if row else 'not_started')}\n"
                f"Время работы: {value('runtime_seconds', ' с')} • Срок: {package['package']['deadline']}\n"
                f"Сделки: {value('trades')} • Открыто: {value('open_positions')} • Закрыто: {value('closed_trades')}\n"
                f"Win Rate: {value('win_rate_pct', '%')}\n"
                f"Доходность за период с начала сессии: {value('period_return_pct', '%')}\n"
                f"Чистый PnL: {value('net_pnl_usdt', ' USDT')}\n"
                f"Реализовано: {value('realized_pnl_usdt', ' USDT')} • Нереализовано: {value('unrealized_pnl_usdt', ' USDT')}\n"
                f"Ожидание на закрытую сделку: {value('expectancy_usdt', ' USDT')} • PF: {pf}\n"
                f"Макс. просадка по закрытым сделкам: {value('max_drawdown_usdt', ' USDT')}\n"
                f"Комиссии: {value('fees_usdt', ' USDT')} • Проскальзывание: {value('slippage_usdt', ' USDT')}\n"
                f"Фандинг: {value('funding_usdt', ' USDT')}\nПропуски данных: {gap_text}\n"
                "Текущая модельная сессия; история отдельно. н/д — данных нет.")
        if row and row.get("startup_held"):
            text += "\nПосле перезапуска нужен ручной запуск."
        if row and row.get("requested") == "stop":
            text += "\nОстановка запрошена; завершение ещё проверяется."
        if details:
            text += (f"\nАдаптер: {package['package']['adapter']}\nСессия: {row['session_id'] if row else 'нет'}\n"
                     f"Рабочий поток: {'работает' if row and row['worker_alive'] else 'не работает'}\n"
                     f"Восстановление: {'ожидается' if row and row.get('recovery_pending') else 'не ожидается'}\n"
                     f"Хранение: {(row or {}).get('persistence_blocker') or 'нет зарегистрированной ошибки'}\n"
                     "Нереализованный PnL — по последней записанной котировке, с учтёнными расходами.\n"
                     "Просадка внутри открытых сделок не измеряется. Месячного прогноза нет.")
            reasons = gaps.get("unavailable_symbols", {})
            if reasons:
                text += "\nПричины пропусков: " + "; ".join(f"{s}: {r}" for s, r in sorted(reasons.items())[:5])
        return TelegramResponse(text, {"inline_keyboard": keyboard})

    def close(self, timeout=10):
        self.stopping.set()
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise TimeoutError("package workers still finalizing; do not start another controller")

    @staticmethod
    def _upload(store, raw):
        package = parse(raw)
        sid, version = package["strategy_id"], package["version"]
        existing = store.db.execute("SELECT 1 FROM packages WHERE strategy_id=? AND version=?", (sid, version)).fetchone()
        if existing:
            row = store.get(sid, version)
            if row["package_sha256"] != sha(canonical(package)):
                return TelegramResponse(f"{sid}/{version}: rejected, ID/version already has different content.")
        else:
            row = store.upload(raw)
        if row["status"] == "uploaded":
            try:
                row = store.validate(sid, version)
            except Exception as exc:
                # Invalid contract remains uploaded; no implicit approval/rejection.
                return TelegramResponse(f"{sid}/{version}: validation FAILED ({type(exc).__name__}). Not approved.")
        return TelegramResponse(f"{sid}/{version}: {row['status']}\nSHA256: {row['package_sha256']}\n"
                                "No strategy started.\n" + HELP)

    def _command(self, store, lifecycle, text):
        parts = text.split()
        command = parts[0] if parts else ""
        if command == "/dashboard":
            if len(parts) != 1:
                return TelegramResponse(HELP)
            counts = sandbox_counts(store.list_packages(), lifecycle.status())
            return TelegramResponse(
                "Sandbox dashboard (strategy versions isolated)\n"
                f"running={counts['running']}; queued={counts['queued']}; "
                f"finished={counts['finished']}; rejected={counts['rejected']}; idle={counts['idle']}\n"
                "Paper-only. Historical and live-shadow results are not combined."
            )
        if command == "/strategies":
            if len(parts) > 2:
                return TelegramResponse(HELP)
            page = int(parts[1]) if len(parts) == 2 else 1
            if page < 1:
                return TelegramResponse("Page must be positive.")
            keys = store.db.execute("SELECT strategy_id,version,status FROM packages ORDER BY strategy_id,version").fetchall()
            sessions = {(r['strategy_id'], r['version']): r for r in lifecycle.status()}
            lines = [f"Strategies page {page}; total {len(keys)}"]
            for sid, version, status in keys[(page - 1) * 5:page * 5]:
                row = sessions.get((sid, version))
                lines.append(f"{sid}/{version}: package={status}; " + self._status(row))
            if self.tick_error:
                lines.append("Scheduler warning: " + self.tick_error)
            return TelegramResponse("\n".join(lines))
        if command not in COMMANDS or len(parts) != 3:
            return TelegramResponse(HELP)
        _, sid, version = parts
        package = store.get(sid, version)
        if command == "/strategy_approve":
            if package["status"] != "approved":
                store.approve(sid, version)
            return TelegramResponse(f"{sid}/{version}: approved. Not queued. Use /strategy_run {sid} {version}")
        if command == "/strategy_reject":
            if package["status"] != "rejected":
                store.reject(sid, version, "explicit authorized Telegram rejection")
            return TelegramResponse(f"{sid}/{version}: rejected.")
        if command == "/strategy_run":
            session_id = lifecycle.enqueue(sid, version)
            return TelegramResponse(f"{sid}/{version}: queue request accepted; session={session_id}. Check status for actual running state.")
        row = next((r for r in lifecycle.status() if (r['strategy_id'], r['version']) == (sid, version)), None)
        if command in {"/strategy_status", "/strategy_dashboard"}:
            if row is None:
                return TelegramResponse(f"{sid}/{version}: package={package['status']}\nno session")
            snapshot = journal_metrics(
                lifecycle.root / "sessions" / row["session_id"], row, package["package"]
            )
            dashboard = self._dashboard_text(package["status"], snapshot)
            if command == "/strategy_status":
                dashboard = self._status(row) + "\n" + dashboard
            return TelegramResponse(dashboard)
        if row is None:
            return TelegramResponse("Package has no session; nothing started or stopped.")
        if command == "/strategy_stop":
            lifecycle.stop(row["session_id"])
            return TelegramResponse(f"{sid}/{version}: stop requested for {row['session_id']}; not yet confirmed stopped.")
        if row["state"] not in TERMINAL or not row["report"]:
            return TelegramResponse("Final report not ready.")
        # Deliver only the exact isolated registry report, never an uploaded path.
        path = lifecycle.root / "sessions" / row["session_id"] / "REPORT.json"
        if path.is_symlink() or not path.is_file() or json.loads(path.read_text()) != json.loads(row["report"]):
            return TelegramResponse("Report unavailable or integrity mismatch; delivery blocked.")
        return TelegramResponse(f"{sid}/{version}: reported (artifact ready); terminal={row['state']}. "
                                "Delivery is confirmed separately.", documents=(str(path),))

    @staticmethod
    def _status(row):
        if row is None:
            return "no session"
        return (f"session={row['session_id']}; state={row['state']}; worker_alive={row['worker_alive']}; "
                f"startup_held={row.get('startup_held', False)}; "
                f"recovery_pending={row['recovery_pending']}; stop_requested={row['requested'] == 'stop'}; "
                f"reported={row['state'] in TERMINAL and bool(row['report'])}; "
                f"storage_blocker={row.get('persistence_blocker', 'none')}")

    @staticmethod
    def _dashboard_text(package_status, data):
        def value(name, suffix=""):
            item = data.get(name)
            return "N/A" if item is None else f"{item}{suffix}"

        runtime = value("runtime_seconds", "s")
        gaps = data.get("data_gaps", {})
        unavailable = gaps.get("unavailable_symbols", {})
        if gaps.get("available"):
            reasons = ", ".join(f"{symbol}:{reason}" for symbol, reason in sorted(unavailable.items())[:5])
            more = f" (+{len(unavailable) - 5} more)" if len(unavailable) > 5 else ""
            gap_text = (f"unavailable={len(unavailable)}; gap_positions={gaps.get('gap_exposed_positions', 0)}; "
                        f"reasons={reasons or 'none'}{more}")
        else:
            gap_text = gaps.get("reason", "unavailable")
        profit_factor = ("infinity (no realized losses)"
                         if data.get("profit_factor_reason") == "no realized losses"
                         else value("profit_factor"))
        return (
            f"{data['strategy_id']}/{data['version']}: package={package_status}; status={data['status']}\n"
            f"scope={data['result_scope']}; runtime={runtime}; deadline={data['deadline']}\n"
            f"trades={value('trades')}; open={value('open_positions')}; closed={value('closed_trades')}\n"
            f"WR={value('win_rate_pct', '%')}; realized={value('realized_pnl_usdt', ' USDT')}; "
            f"unrealized={value('unrealized_pnl_usdt', ' USDT')}\n"
            f"net PnL={value('net_pnl_usdt', ' USDT')}; period return={value('period_return_pct', '%')}\n"
            f"expectancy={value('expectancy_usdt', ' USDT/closed')}; PF={profit_factor}; "
            f"max DD (closed realized)={value('max_drawdown_usdt', ' USDT')}\n"
            f"fees={value('fees_usdt', ' USDT')}; slippage={value('slippage_usdt', ' USDT')}; "
            f"funding={value('funding_usdt', ' USDT')}\n"
            f"data gaps: {gap_text}\n"
            "Historical: not attached; never combined with live-shadow.\n"
            "Monthly projection: not calculated."
        )

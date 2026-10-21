import contextlib
import ast
import html
import io
import re
import sqlite3
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import Mock, patch

import agent_google
import agent_images
import agent_notas
import agent_pc
import agent_search
import agent_screen
import ai_provider_manager
import idiomas


def _sin_tildes(texto):
    return "".join(
        caracter for caracter in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caracter) != "Mn"
    )


class GmailConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.original_context = agent_google._ctx
        self.original_pending = agent_google._correo_pendiente
        agent_google._ctx = {"quitar_tildes": _sin_tildes}
        agent_google._correo_pendiente = None
        for mocked in (
            patch.object(agent_google, "_hablar"),
            patch.object(agent_google, "_bridge_html"),
            patch.object(agent_google, "_bridge_scroll"),
            patch.object(agent_google, "_burbuja", side_effect=lambda value: value),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)

    def tearDown(self):
        agent_google._correo_pendiente = self.original_pending
        agent_google._ctx = self.original_context

    def test_visible_confirmation_phrase_sends_only_after_confirmation(self):
        with patch.object(agent_google, "_enviar_correo_confirmado") as send:
            agent_google.gmail_enviar("test@example.com", "Prueba", "Contenido")
            self.assertTrue(agent_google.hay_correo_pendiente())

            consumed = agent_google.resolver_correo_pendiente("sí, envíalo")

            self.assertTrue(consumed)
            send.assert_called_once_with(
                "test@example.com", "Prueba", "Contenido", None, ""
            )
            self.assertFalse(agent_google.hay_correo_pendiente())

    def test_cancel_does_not_send_email(self):
        with patch.object(agent_google, "_enviar_correo_confirmado") as send:
            agent_google.gmail_enviar("test@example.com", "Prueba", "Contenido")
            self.assertTrue(agent_google.resolver_correo_pendiente("cancela"))
            send.assert_not_called()
            self.assertFalse(agent_google.hay_correo_pendiente())

    def test_ambiguous_confirmation_does_not_send_or_consume_pending_email(self):
        with patch.object(agent_google, "_enviar_correo_confirmado") as send:
            agent_google.gmail_enviar("test@example.com", "Prueba", "Contenido")

            consumed = agent_google.resolver_correo_pendiente("sí, no")

            self.assertFalse(consumed)
            self.assertTrue(agent_google.hay_correo_pendiente())
            send.assert_not_called()

    def test_saved_contact_alias_becomes_gmail_from_filter(self):
        agent_google._ctx["obtener_contacto_confianza"] = lambda name: (
            {"correo": "mami@example.test"} if name.lower() == "mami" else None
        )
        query = agent_google._preparar_consulta_gmail(
            "Muéstrame los últimos emails que me hayan llegado de Mami"
        )
        self.assertEqual(query, "from:mami@example.test")

    def test_natural_nasa_mail_request_routes_to_gmail_with_sender_and_topic(self):
        source = Path(__file__).resolve().parents[1] / "Jarvis_main.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        needed = {"_intentar_comando_directo", "_COMANDOS_DIRECTOS"}
        nodes = [node for node in tree.body if
                 (isinstance(node, ast.FunctionDef) and node.name in needed) or
                 (isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id in needed for target in node.targets
                 ))]
        namespace = {
            "re": re, "quitar_tildes": _sin_tildes, "apps": {},
            "_comando_personalizado": lambda _text: None,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
        action = namespace["_intentar_comando_directo"](
            "Busca correos que me haya enviado la NASA sobre NASA Space Apps Challenge"
        )
        self.assertEqual(action["accion"], "gmail_buscar")
        self.assertEqual(action["params"]["consulta"], 'from:"nasa" nasa space apps challenge')

    def test_sent_by_nasa_and_space_apps_topic_become_gmail_search_query(self):
        query = agent_google._preparar_consulta_gmail(
            'from:"NASA" NASA Space Apps Challenge'
        )
        self.assertIn('from:"NASA"', query)
        self.assertIn("Space", query)

    def test_invalid_double_dot_email_is_rejected_before_confirmation(self):
        with patch.object(agent_google, "_hablar") as speak, \
             patch.object(agent_google, "_enviar_correo_confirmado") as send:
            agent_google.gmail_enviar("spiderroyale12@gmail..com", "Test", "Body")
        self.assertFalse(agent_google.hay_correo_pendiente())
        speak.assert_called_once()
        send.assert_not_called()


class GoogleActionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.original_context = agent_google._ctx
        agent_google._ctx = {
            "hablar": lambda *args, **kwargs: None,
            "quitar_tildes": _sin_tildes,
        }

    def tearDown(self):
        agent_google._ctx = self.original_context

    def test_calendar_delete_does_not_delete_an_unmatched_event(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "event-1", "summary": "Reunión de equipo"}]
        }
        with patch.object(agent_google, "_calendar", return_value=service):
            agent_google.calendar_eliminar_evento("cita del dentista")
        service.events.return_value.delete.assert_not_called()

    def test_invalid_calendar_date_does_not_create_an_event(self):
        service = Mock()
        with patch.object(agent_google, "_calendar", return_value=service):
            agent_google.calendar_crear_evento(
                "crear evento reunión 31/02/2026 a las 25"
            )
        service.events.return_value.insert.assert_not_called()

    def test_drive_search_escapes_quotes_in_api_query(self):
        service = Mock()
        service.files.return_value.list.return_value.execute.return_value = {"files": []}
        with patch.object(agent_google, "_drive", return_value=service):
            agent_google.drive_buscar("O'Brien")
        query = service.files.return_value.list.call_args.kwargs["q"]
        self.assertIn("trashed=false", query)
        self.assertIn("fullText contains 'O'", query)
        self.assertIn("fullText contains 'Brien'", query)

    def test_calendar_edit_accepts_date_without_replacing_title(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {
            "items": [{
                "id": "event-1", "summary": "Reunión de equipo",
                "start": {"dateTime": "2026-10-20T09:30:00-05:00"},
                "end": {"dateTime": "2026-10-20T10:15:00-05:00"},
            }]
        }
        with patch.object(agent_google, "_calendar", return_value=service):
            agent_google.calendar_editar_evento("reunión de equipo", fecha_str="2026-10-22")
        body = service.events.return_value.patch.call_args.kwargs["body"]
        self.assertNotIn("summary", body)
        self.assertIn("2026-10-22T09:30:00", body["start"]["dateTime"])
        self.assertIn("2026-10-22T10:15:00", body["end"]["dateTime"])
        service.events.return_value.patch.assert_called_once()
        service.events.return_value.update.assert_not_called()

    def test_title_match_reports_ambiguous_names_instead_of_picking_arbitrarily(self):
        items = [{"title": "Comprar leche"}, {"title": "Comprar leche y huevos"}]
        match, ambiguous = agent_google._coincidencia_por_titulo(items, "comprar", "title")
        self.assertIsNone(match)
        self.assertTrue(ambiguous)

    def test_gmail_results_escape_untrusted_subject_and_sender(self):
        service = Mock()
        messages = service.users.return_value.messages.return_value
        messages.list.return_value.execute.return_value = {"messages": [{"id": "msg-1"}]}
        messages.get.return_value.execute.return_value = {
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "<script>subject</script>"},
                    {"name": "From", "value": "<img src=x>"},
                    {"name": "Date", "value": "today"},
                ]
            }
        }
        with patch.object(agent_google, "_gmail", return_value=service), \
             patch.object(agent_google, "_bridge_html") as render, \
             patch.object(agent_google, "_bridge_scroll"), \
             patch.object(agent_google, "_burbuja", side_effect=lambda value: value):
            agent_google.gmail_leer()
        html = render.call_args.args[0]
        self.assertNotIn("<script>subject</script>", html)
        self.assertNotIn("<img src=x>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)


class ProviderRedactionTests(unittest.TestCase):
    def test_redacts_query_credentials_and_authorization(self):
        message = (
            "request https://example.test/path?key=FAKE_SECRET&x=1 "
            "api_key=OTHER_SECRET Authorization: Bearer TOKEN_SECRET"
        )
        redacted = ai_provider_manager._redact_sensitive_text(message)
        self.assertNotIn("FAKE_SECRET", redacted)
        self.assertNotIn("OTHER_SECRET", redacted)
        self.assertNotIn("TOKEN_SECRET", redacted)
        self.assertIn("key=[REDACTED]", redacted)


class GroqSearchErrorTests(unittest.TestCase):
    def test_search_error_shows_real_http_status_and_provider_detail(self):
        original = agent_search._ctx
        bridge = Mock()
        agent_search._ctx = {
            "KEYS_LISTAS": __import__("threading").Event(),
            "groq_keys": lambda: ["test-key"],
            "groq_key_activa": lambda: "test-key",
            "groq_rotar_key": lambda *_args: None,
            "GROQ_MODEL": "openai/gpt-oss-120b",
            "GROQ_MODELOS_FALLBACK": [],
            "GROQ_BASE_URL": "https://example.test/chat",
            "idioma_respuesta": lambda: "es",
            "html_burbuja_jarvis": lambda value: value,
            "hablar": lambda *_args, **_kwargs: None,
            "bridge": bridge,
        }
        agent_search._ctx["KEYS_LISTAS"].set()
        response = Mock(status_code=403, text="forbidden")
        response.json.return_value = {"error": {"message": "Project has no access to model."}}
        try:
            with patch.object(agent_search.requests, "post", return_value=response):
                self.assertFalse(agent_search._buscar_con_groq("consulta de prueba"))
            mensaje = bridge.append_html.emit.call_args.args[0]
            self.assertIn("HTTP 403", mensaje)
            self.assertIn("Project has no access to model", mensaje)
            self.assertNotIn("Revisa que la clave tenga acceso a GPT-OSS", mensaje)
        finally:
            agent_search._ctx = original

    def test_gemini_failure_log_does_not_include_key_from_url(self):
        fake_key = "FAKE_GEMINI_KEY_FOR_TEST"

        class FailingResponse:
            status_code = 200
            text = ""

            def raise_for_status(self):
                raise ai_provider_manager.requests.HTTPError(
                    "request failed: "
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"test-model:generateContent?key={fake_key}"
                )

        with tempfile.TemporaryDirectory(prefix="jarvis-provider-test-") as directory:
            manager = ai_provider_manager.AIProviderManager(
                str(Path(directory) / "providers.json")
            )
            manager.add_custom_provider(
                "gemini",
                model="test-model",
                base_url="Gemini",
                provider_type="gemini",
                api_keys=[fake_key],
            )
            output = io.StringIO()
            with patch.object(
                ai_provider_manager.requests, "post", return_value=FailingResponse()
            ), contextlib.redirect_stdout(output):
                with self.assertRaises(RuntimeError):
                    manager.generate("test", preferred="gemini")

            self.assertNotIn(fake_key, output.getvalue())
            self.assertIn("key=[REDACTED]", output.getvalue())

    def test_gemini_error_body_does_not_include_key_from_url(self):
        fake_key = "FAKE_GEMINI_BODY_KEY_FOR_TEST"

        class ErrorResponse:
            status_code = 500
            text = (
                "upstream failed at "
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"test-model:generateContent?key={fake_key}"
            )

            def raise_for_status(self):
                raise AssertionError("The error response must not reach this call")

        with tempfile.TemporaryDirectory(prefix="jarvis-provider-test-") as directory:
            manager = ai_provider_manager.AIProviderManager(
                str(Path(directory) / "providers.json")
            )
            manager.add_custom_provider(
                "gemini",
                model="test-model",
                base_url="Gemini",
                provider_type="gemini",
                api_keys=[fake_key],
            )
            output = io.StringIO()
            with patch.object(
                ai_provider_manager.requests, "post", return_value=ErrorResponse()
            ), contextlib.redirect_stdout(output):
                with self.assertRaises(RuntimeError):
                    manager.generate("test", preferred="gemini")

            self.assertNotIn(fake_key, output.getvalue())
            self.assertIn("key=[REDACTED]", output.getvalue())

    def test_groq_and_gemini_success_responses_are_parsed(self):
        class SuccessResponse:
            status_code = 200
            text = ""

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{"message": {"content": "Groq OK"}}],
                    "candidates": [{"content": {"parts": [{"text": "Gemini OK"}]}}],
                }

        with tempfile.TemporaryDirectory(prefix="jarvis-provider-test-") as directory:
            manager = ai_provider_manager.AIProviderManager(
                str(Path(directory) / "providers.json")
            )
            manager.add_custom_provider(
                "groq", model="test-model", base_url="Groq",
                api_keys=["FAKE_GROQ_KEY"],
            )
            manager.add_custom_provider(
                "gemini", model="test-model", base_url="Gemini",
                provider_type="gemini", api_keys=["FAKE_GEMINI_KEY"],
            )
            with patch.object(
                ai_provider_manager.requests, "post", return_value=SuccessResponse()
            ):
                self.assertEqual(
                    manager._call_openai_compatible("groq", "test"), "Groq OK"
                )
                self.assertEqual(manager._call_gemini("gemini", "test"), "Gemini OK")

    def test_gemini_discovery_can_preview_without_overwriting_saved_models(self):
        class ModelsResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "models": [
                        {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                        {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
                        {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
                    ]
                }

        with tempfile.TemporaryDirectory(prefix="jarvis-model-discovery-") as directory:
            manager = ai_provider_manager.AIProviderManager(str(Path(directory) / "providers.json"))
            manager.add_custom_provider(
                "gemini", model="gemini-2.5-flash", base_url="Gemini",
                provider_type="gemini", api_keys=["FAKE_GEMINI_KEY"],
            )
            with patch.object(ai_provider_manager.requests, "get", return_value=ModelsResponse()) as request:
                discovered = manager.discover_provider_models("gemini", guardar=False)
            self.assertIn("gemini-3.8-flash", discovered)
            self.assertNotIn("gemini-embedding-001", discovered)
            self.assertNotIn("gemini-2.0-flash", discovered)
            self.assertEqual(manager.get_provider_models("gemini"), ["gemini-2.5-flash"])
            request.assert_called_once()

            manager.set_provider_models("gemini", discovered)
            self.assertEqual(manager.get_provider("gemini")["model"], "")


class LocalStorageTests(unittest.TestCase):
    def test_notes_memory_and_safe_routine_use_temporary_database(self):
        original_db = agent_notas._DB_FILE
        original_context = agent_notas._ctx
        with tempfile.TemporaryDirectory(prefix="jarvis-notes-test-") as directory:
            db_path = str(Path(directory) / "notes.sqlite3")
            agent_notas._DB_FILE = db_path
            agent_notas._ctx = {
                "base_path": directory,
                "config": {},
                "hablar": lambda *args, **kwargs: None,
            }
            try:
                with patch.object(agent_notas, "_bridge_html"), \
                     patch.object(agent_notas, "_bridge_scroll"), \
                     patch.object(agent_notas, "_burbuja", side_effect=lambda value: value):
                    agent_notas._init_db()
                    note_id = agent_notas.nota_crear("texto temporal", "auditoria")
                    agent_notas.nota_editar(
                        str(note_id), contenido="actualizado", titulo_nuevo="auditoria editada"
                    )
                    agent_notas.nota_buscar("actualizado")
                    agent_notas.nota_leer(id=note_id)
                    agent_notas.memoria_guardar("alias", "contacto de prueba")
                    agent_notas.rutina_crear(
                        "auditoria",
                        [
                            {"accion": "abrir_app", "params": {"nombre": "Calculadora"}},
                            {"accion": "apagar", "params": {}},
                        ],
                    )

                    import sqlite3
                    connection = sqlite3.connect(db_path)
                    try:
                        self.assertEqual(
                            connection.execute(
                                "SELECT titulo, contenido FROM notas WHERE id=?", (note_id,)
                            ).fetchone(),
                            ("auditoria editada", "actualizado"),
                        )
                        self.assertEqual(
                            connection.execute(
                                "SELECT valor FROM memoria_sesion WHERE clave='alias'"
                            ).fetchone(),
                            ("contacto de prueba",),
                        )
                        routine = connection.execute(
                            "SELECT acciones FROM rutinas WHERE nombre='auditoria'"
                        ).fetchone()[0]
                        self.assertIn("abrir_app", routine)
                        self.assertNotIn("apagar", routine)
                    finally:
                        connection.close()
                    agent_notas.nota_eliminar(str(note_id))
                    connection = sqlite3.connect(db_path)
                    try:
                        self.assertEqual(
                            connection.execute("SELECT COUNT(*) FROM notas").fetchone()[0], 0
                        )
                    finally:
                        connection.close()
            finally:
                agent_notas._DB_FILE = original_db
                agent_notas._ctx = original_context


class NotesInputValidationTests(unittest.TestCase):
    def test_invalid_alarm_and_reminder_times_are_rejected_without_raising(self):
        for value in ("99:99", "24:00", "12:60", "en 999999999999999999999 horas"):
            with self.subTest(value=value):
                self.assertIsNone(agent_notas._parsear_hora_alarma(value))

        for value in ("99:99", "24:00", "12:60", "2026-99-99 99:99"):
            with self.subTest(value=value):
                self.assertIsNone(agent_notas._parsear_fecha_hora(value))

    def test_reminder_minutes_validate_types_and_allow_immediate_reminder(self):
        self.assertIsNone(agent_notas._parsear_fecha_hora("", minutos="invalid"))
        self.assertIsNone(agent_notas._parsear_fecha_hora("", minutos=-1))
        self.assertIsNotNone(agent_notas._parsear_fecha_hora("", minutos=0))

    def test_notes_escape_untrusted_text_when_no_markdown_renderer_is_configured(self):
        original_db = agent_notas._DB_FILE
        original_context = agent_notas._ctx
        with tempfile.TemporaryDirectory(prefix="jarvis-note-html-test-") as directory:
            agent_notas._DB_FILE = str(Path(directory) / "notes.sqlite3")
            agent_notas._ctx = {
                "base_path": directory,
                "hablar": lambda *args, **kwargs: None,
            }
            try:
                agent_notas._init_db()
                with patch.object(agent_notas, "_bridge_html") as render, \
                     patch.object(agent_notas, "_bridge_scroll"), \
                     patch.object(agent_notas, "_burbuja", side_effect=lambda value: value):
                    note_id = agent_notas.nota_crear("<img src=x onerror=alert(1)>", "<script>title</script>")
                    agent_notas.nota_leer(id=note_id)
                    rendered = "".join(call.args[0] for call in render.call_args_list)
                    self.assertNotIn("<script>title</script>", rendered)
                    self.assertNotIn("<img src=x onerror=alert(1)>", rendered)
                    self.assertIn("&lt;script&gt;", rendered)
                    self.assertIn("&lt;img", rendered)
            finally:
                agent_notas._DB_FILE = original_db
                agent_notas._ctx = original_context

    def test_local_note_alarm_reminder_memory_contact_and_routine_flows(self):
        original_db = agent_notas._DB_FILE
        original_context = agent_notas._ctx
        with tempfile.TemporaryDirectory(prefix="jarvis-local-command-test-") as directory:
            db_path = str(Path(directory) / "local.sqlite3")
            executed = []
            perfil = {"nombre": "Emiliano", "hobbies": ["lectura"]}
            agent_notas._DB_FILE = db_path
            agent_notas._ctx = {
                "base_path": directory,
                "config": {},
                "hablar": lambda *args, **kwargs: None,
                "memoria_usuario": perfil,
                "guardar_memoria": lambda value: None,
                "ejecutar_accion": lambda action, widget: executed.append(action),
            }
            try:
                agent_notas._init_db()

                def consultar(sql, parametros=()):
                    connection = sqlite3.connect(db_path)
                    try:
                        return connection.execute(sql, parametros).fetchone()
                    finally:
                        connection.close()

                with patch.object(agent_notas, "_bridge_html"), \
                     patch.object(agent_notas, "_bridge_scroll"), \
                     patch.object(agent_notas, "_burbuja", side_effect=lambda value: value):
                    note_id = agent_notas.nota_crear("Proyecto de prueba", "Proyecto")
                    agent_notas.nota_buscar("Proyecto")
                    agent_notas.nota_editar(str(note_id), contenido="Actualizado")
                    agent_notas.nota_leer(id=note_id)

                    agent_notas.alarma_crear("23:59", "Prueba de alarma")
                    agent_notas.alarma_listar()
                    alarm_id = consultar(
                        "SELECT id FROM alarmas WHERE etiqueta=?", ("Prueba de alarma",)
                    )[0]
                    agent_notas.alarma_eliminar(str(alarm_id))

                    agent_notas.recordatorio_crear(
                        "Seguimiento de prueba", minutos=30, acompanamiento=True
                    )
                    agent_notas.recordatorio_listar()
                    agent_notas.recordatorio_confirmar("Seguimiento de prueba")
                    agent_notas.recordatorio_crear("Eliminar prueba", minutos=40)
                    agent_notas.recordatorio_eliminar("Eliminar prueba")
                    self.assertIsNone(consultar(
                        "SELECT id FROM recordatorios WHERE texto='Eliminar prueba'"
                    ))
                    agent_notas.recordatorio_crear("Revisar correo", minutos=50)
                    agent_notas.recordatorio_editar("Revisar correo", texto_nuevo="Revisar correo NASA")
                    self.assertEqual(
                        consultar("SELECT texto FROM recordatorios WHERE texto LIKE 'Revisar correo NASA%' ")[0],
                        "Revisar correo NASA",
                    )
                    agent_notas.acompanamiento_resumen()

                    agent_notas.contacto_confianza_guardar(
                        "Contacto QA", "qa@example.test", "correo"
                    )
                    self.assertEqual(
                        agent_notas.contacto_confianza_obtener("Contacto QA")["correo"],
                        "qa@example.test",
                    )
                    agent_notas.contactos_confianza_listar()
                    agent_notas.contacto_confianza_eliminar("Contacto QA")

                    agent_notas.memoria_guardar("proyecto", "prueba local", "trabajo")
                    agent_notas.memoria_leer("proyecto")
                    agent_notas.memoria_buscar("prueba local")
                    agent_notas.memoria_resumir()
                    agent_notas.memoria_exportar()
                    self.assertEqual(len(list(Path(directory).glob("jarvis_memoria_export_*.json"))), 1)
                    agent_notas.memoria_olvidar("proyecto")
                    agent_notas.memoria_guardar("temporal", "borrar")
                    agent_notas.memoria_limpiar()

                    agent_notas.rutina_crear(
                        "Rutina QA",
                        [
                            {"accion": "subir_volumen", "params": {"porcentaje": 1}},
                            {"accion": "apagar", "params": {}},
                        ],
                    )
                    agent_notas.rutina_listar()
                    agent_notas.rutina_previsualizar("Rutina QA")
                    agent_notas.rutina_programar("Rutina QA", "en 30 minutos")
                    agent_notas.rutina_pausar("Rutina QA")
                    agent_notas.rutina_pausar("Rutina QA", pausar=False)
                    agent_notas.rutina_ejecutar("Rutina QA")
                    agent_notas.rutina_historial("Rutina QA")
                    self.assertEqual([item["accion"] for item in executed], ["subir_volumen"])

                    connection = sqlite3.connect(db_path)
                    try:
                        connection.execute(
                            "UPDATE rutinas SET acciones=? WHERE lower(nombre)=?",
                            ('[{"accion":"apagar","params":{}}]', "rutina qa"),
                        )
                        connection.commit()
                    finally:
                        connection.close()
                    agent_notas.rutina_ejecutar("Rutina QA")
                    agent_notas.nota_eliminar(str(note_id))
                    agent_notas.memoria_guardar("residuo", "limpiar perfil")
                    agent_notas.memoria_borrar_todo()

                    self.assertEqual(consultar("SELECT COUNT(*) FROM notas")[0], 0)
                    self.assertEqual(consultar("SELECT COUNT(*) FROM memoria_sesion")[0], 0)
                    self.assertEqual(consultar("SELECT COUNT(*) FROM rutinas_log")[0], 1)
                    self.assertIsNone(perfil["nombre"])
            finally:
                agent_notas._DB_FILE = original_db
                agent_notas._ctx = original_context


class CommandRouterValidationTests(unittest.TestCase):
    def test_pc_volume_router_uses_safe_default_and_clamps_out_of_range_values(self):
        with patch.object(agent_pc, "poner_volumen") as set_volume:
            self.assertTrue(agent_pc.ejecutar("poner_volumen", {"porcentaje": "bad"}))
            set_volume.assert_called_once_with(50, None)
            set_volume.reset_mock()
            agent_pc.ejecutar("poner_volumen", {"porcentaje": 999})
            set_volume.assert_called_once_with(100, None)

    def test_google_mail_read_limits_and_invalid_router_payloads(self):
        with patch.object(agent_google, "gmail_leer") as read_mail:
            self.assertTrue(agent_google.ejecutar("gmail_leer", {"max_msgs": "bad"}))
            read_mail.assert_called_once_with(5, None)
            read_mail.reset_mock()
            agent_google.ejecutar("gmail_leer", {"max_msgs": 999})
            read_mail.assert_called_once_with(20, None)

    def test_search_router_accepts_missing_or_non_dict_payloads(self):
        with patch.object(agent_search, "calcular_expresion", return_value=True) as calculate:
            self.assertTrue(agent_search.ejecutar("calcular", None))
            calculate.assert_called_once_with("", None)

    def test_image_gallery_escapes_labels_and_rejects_unsafe_image_urls(self):
        html = agent_images.html_galeria(
            "<script>title</script>",
            ["javascript:alert(1)", "https://images.example.test/photo.jpg?x=1&y=2"],
        )
        self.assertNotIn("<script>title</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("javascript:", html)
        self.assertIn("https://images.example.test/photo.jpg?x=1&amp;y=2", html)

        class InlineThread:
            def __init__(self, target, daemon=True):
                self.target = target

            def start(self):
                self.target()

        with patch.object(agent_images.threading, "Thread", InlineThread), \
             patch.object(agent_images, "buscar_imagenes", return_value=[]), \
             patch.object(agent_images, "_bridge_html") as render, \
             patch.object(agent_images, "_bridge_scroll"), \
             patch.object(agent_images, "_burbuja", side_effect=lambda value: value):
            agent_images.ejecutar("buscar", {"termino": "<script>query</script>"})
        self.assertNotIn("<script>query</script>", render.call_args.args[0])
        self.assertIn("&lt;script&gt;", render.call_args.args[0])

    def test_screen_calibration_handles_bad_duration_and_caps_it(self):
        with patch.object(agent_screen, "calibrar_gestos", return_value=True) as calibrate:
            self.assertTrue(agent_screen.ejecutar("calibrar_gestos", {"duracion": "bad"}))
            calibrate.assert_called_once_with(6, None)
            calibrate.reset_mock()
            agent_screen.ejecutar("calibrar_gestos", {"duracion": 999})
            calibrate.assert_called_once_with(30, None)


class CommandDispatchSmokeTests(unittest.TestCase):
    """Exercise every agent dispatcher branch without external side effects."""

    def _check_routes(self, module, routes, payloads=None):
        payloads = payloads or {}
        for action, target in routes.items():
            with self.subTest(module=module.__name__, action=action):
                if module is agent_images and action == "buscar":
                    handler_result = []
                elif module is agent_images and action == "generar":
                    handler_result = False
                else:
                    handler_result = True
                with patch.object(module, target, return_value=handler_result) as handler:
                    result = module.ejecutar(action, payloads.get(action, {}))
                if action in {"buscar", "generar"} and module is agent_images:
                    # Image generation is an explicit placeholder and returns
                    # the target's False result by design.
                    self.assertEqual(result, action != "generar")
                elif module is agent_screen and action in {"ver_pantalla", "analizar_pantalla"}:
                    self.assertIsNone(result)
                else:
                    self.assertTrue(result)
                handler.assert_called_once()

    def test_pc_dispatch_routes_are_connected_without_touching_the_pc(self):
        routes = {
            "abrir": "abrir_app", "cerrar": "cerrar_app",
            "minimizar": "minimizar_app", "maximizar": "maximizar_app",
            "poner_volumen": "poner_volumen", "subir_volumen": "subir_volumen",
            "bajar_volumen": "bajar_volumen", "mute": "mute_volumen",
            "subir_brillo": "subir_brillo", "bajar_brillo": "bajar_brillo",
            "poner_brillo": "set_brightness", "apagar": "apagar_pc",
            "reiniciar": "reiniciar_pc", "bloquear": "bloquear_pc",
            "suspender": "suspender_pc", "hibernar": "hibernar_pc",
            "modo": "activar_modo", "buscar_archivo": "buscar_y_abrir_archivo",
            "aprender_app": "aprender_app", "resolver_destino": "resolver_destino_pendiente",
        }
        payloads = {
            "buscar_archivo": {"termino": "archivo de prueba"},
            "aprender_app": {"nombre": "prueba", "ruta": "C:/prueba.exe"},
        }
        self._check_routes(agent_pc, routes, payloads)

    def test_google_dispatch_routes_are_connected_without_account_calls(self):
        routes = {
            "gmail_leer": "gmail_leer", "gmail_buscar": "gmail_buscar",
            "gmail_enviar": "gmail_enviar", "gmail_eliminar": "gmail_eliminar",
            "ver_eventos": "calendar_ver_eventos", "crear_evento": "calendar_crear_evento",
            "editar_evento": "calendar_editar_evento", "eliminar_evento": "calendar_eliminar_evento",
            "ver_tareas": "tasks_ver", "crear_tarea": "tasks_crear",
            "editar_tarea": "tasks_editar", "eliminar_tarea": "tasks_eliminar",
            "buscar_contacto": "contactos_buscar", "drive_buscar": "drive_buscar",
        }
        self._check_routes(agent_google, routes)

    def test_notes_dispatch_routes_are_connected_with_handlers_stubbed(self):
        routes = {
            "nota_crear": "nota_crear", "nota_leer": "nota_leer",
            "nota_buscar": "nota_buscar", "nota_editar": "nota_editar",
            "nota_eliminar": "nota_eliminar", "alarma_crear": "alarma_crear",
            "alarma_listar": "alarma_listar", "alarma_eliminar": "alarma_eliminar",
            "recordatorio_crear": "recordatorio_crear", "recordatorio_listar": "recordatorio_listar",
            "recordatorio_eliminar": "recordatorio_eliminar", "recordatorio_confirmar": "recordatorio_confirmar",
            "recordatorio_editar": "recordatorio_editar",
            "acompanamiento_resumen": "acompanamiento_resumen",
            "contacto_confianza_guardar": "contacto_confianza_guardar",
            "contactos_confianza_listar": "contactos_confianza_listar",
            "contacto_confianza_eliminar": "contacto_confianza_eliminar",
            "memoria_guardar": "memoria_guardar", "memoria_leer": "memoria_leer",
            "memoria_resumir": "memoria_resumir", "memoria_buscar": "memoria_buscar",
            "memoria_olvidar": "memoria_olvidar", "memoria_exportar": "memoria_exportar",
            "memoria_limpiar": "memoria_limpiar", "memoria_borrar_todo": "memoria_borrar_todo",
            "rutina_crear": "rutina_crear", "rutina_listar": "rutina_listar",
            "rutina_previsualizar": "rutina_previsualizar", "rutina_ejecutar": "rutina_ejecutar",
            "rutina_programar": "rutina_programar", "rutina_pausar": "rutina_pausar",
            "rutina_reanudar": "rutina_pausar", "rutina_historial": "rutina_historial",
        }
        self._check_routes(agent_notas, routes)

    def test_search_and_image_dispatch_routes_are_connected_without_network(self):
        self._check_routes(agent_search, {
            "buscar_web": "buscar_web", "noticias": "obtener_noticias",
            "clima": "obtener_clima", "calcular": "calcular_expresion",
            "traducir": "traducir_texto",
        })
        routes = {"buscar": "buscar_imagenes", "generar": "generar_imagen"}
        image_payloads = {
            "buscar": {"termino": "imagen de prueba"},
            "generar": {"prompt": "imagen de prueba"},
        }
        class InlineThread:
            def __init__(self, target, daemon=True):
                self.target = target

            def start(self):
                self.target()

        with patch.object(agent_images.threading, "Thread", InlineThread), \
             patch.object(agent_images, "_bridge_html"), \
             patch.object(agent_images, "_bridge_scroll"), \
             patch.object(agent_images, "_burbuja", side_effect=lambda value: value):
            self._check_routes(agent_images, routes, image_payloads)
        with patch.object(agent_images, "_bridge_html"), patch.object(agent_images, "_bridge_scroll"), \
             patch.object(agent_images, "_burbuja", side_effect=lambda value: value):
            with patch.object(agent_images, "html_galeria", return_value="<p>ok</p>"):
                self.assertTrue(agent_images.ejecutar("galeria", {"urls": ["https://example.test/a.jpg"]}))

    def test_screen_dispatch_routes_are_connected_without_mouse_camera_or_keyboard(self):
        routes = {
            "activar_gestos": "activar_modo_gestos", "desactivar_gestos": "desactivar_modo_gestos",
            "calibrar_gestos": "calibrar_gestos", "recalibrar_gestos": "recalibrar_modo_gestos",
            "hacer_click": "hacer_click", "escribir": "escribir", "desplazarse": "desplazarse",
            "hacer_zoom": "hacer_zoom",
        }
        self._check_routes(agent_screen, routes)
        with patch.object(agent_screen, "_notify"), patch.object(agent_screen, "_say"):
            self.assertIsNone(agent_screen.ejecutar("ver_pantalla", {}))
        context = {"analizar_pantalla": lambda *args: None}
        with patch.object(agent_screen, "_ctx", context):
            self.assertIsNone(agent_screen.ejecutar("analizar_pantalla", {}))


class NaturalLanguageCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_path = Path(__file__).resolve().parents[1] / "Jarvis_main.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        needed = {
            "_intentar_comando_directo", "_es_consulta_meteorologica",
            "_COMANDOS_DIRECTOS", "_SITIOS_WEB", "validar_config", "_markdown_a_html",
        }
        nodes = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in needed:
                nodes.append(node)
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in needed for target in node.targets
            ):
                nodes.append(node)

        def quitar_tildes(texto):
            return "".join(
                char for char in unicodedata.normalize("NFD", str(texto))
                if unicodedata.category(char) != "Mn"
            )

        namespace = {
            "re": re,
            "quitar_tildes": quitar_tildes,
            "apps": {},
            "_comando_personalizado": lambda _texto: None,
            "idiomas": idiomas,
            "_html_mod": html,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)
        cls.parser = staticmethod(namespace["_intentar_comando_directo"])

    def test_common_spanish_phrases_map_to_the_expected_actions(self):
        examples = {
            "sube el volumen": "subir_volumen",
            "muéstrame mis eventos": "ver_eventos",
            "mis notas": "nota_leer",
            "recuérdame comprar leche en 20 minutos": "recordatorio_crear",
            "abre Spotify": "abrir_app",
            "qué tiempo hace en Bogotá": "clima",
            "haz clic en 100, 200": "hacer_click",
            "apaga el pc": "apagar",
            "Jarvis pon una alarma en 10 minutos": "alarma_crear",
            "quita la alarma número 2": "alarma_eliminar",
            "borra el recordatorio comprar leche": "recordatorio_eliminar",
            "cambia el recordatorio estudiar por estudiar matemáticas": "recordatorio_editar",
            "maximiza Chrome": "maximizar_app",
            "deszoom": "hacer_zoom",
            "busca Shrek 5 en Google Edge": "abrir_busqueda_navegador",
            "busca Avengers Doomsday en Chrome": "abrir_busqueda_navegador",
            "Busca correos que me haya enviado la NASA sobre NASA Space Apps Challenge": "gmail_buscar",
        }
        for phrase, expected in examples.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(self.parser(phrase)["accion"], expected)

    def test_browser_search_keeps_engine_and_browser_intent(self):
        edge = self.parser("busca Shrek 5 en Google Edge")
        self.assertEqual(edge["params"], {"consulta": "shrek 5", "motor": "google", "navegador": "edge"})
        chrome = self.parser("busca Avengers Doomsday en Chrome")
        self.assertEqual(chrome["params"], {"consulta": "avengers doomsday", "motor": "google", "navegador": "chrome"})


class ScreenZoomTests(NaturalLanguageCommandTests):
    def test_zoom_uses_application_shortcuts_for_in_out_and_reset(self):
        if agent_screen.pyautogui is None:
            self.skipTest("pyautogui no está instalado en este entorno")
        with patch.object(agent_screen, "_require_control", return_value=True), \
             patch.object(agent_screen, "_notify"), patch.object(agent_screen, "_say"), \
             patch.object(agent_screen.pyautogui, "hotkey") as hotkey:
            agent_screen.hacer_zoom(240)
            self.assertEqual(hotkey.call_args_list, [unittest.mock.call("ctrl", "="), unittest.mock.call("ctrl", "=")])
            hotkey.reset_mock()
            agent_screen.hacer_zoom(-240)
            self.assertEqual(hotkey.call_args_list, [unittest.mock.call("ctrl", "-"), unittest.mock.call("ctrl", "-")])
            hotkey.reset_mock()
            agent_screen.hacer_zoom(0)
            hotkey.assert_called_once_with("ctrl", "0")

    def test_non_weather_use_of_tiempo_is_not_routed_to_weather(self):
        self.assertIsNone(self.parser("qué tiempo libre tengo esta semana"))
        self.assertIsNone(self.parser("qué tiempo tengo para estudiar"))

    def test_invalid_infinite_accessibility_limit_uses_default(self):
        config = self.parser.__globals__["validar_config"]({
            "lectura_pantalla_max_caracteres": float("inf"),
            "comandos_personalizados": {},
        })
        self.assertEqual(config["lectura_pantalla_max_caracteres"], 900)

    def test_markdown_converter_escapes_raw_html_before_formatting(self):
        rendered = self.parser.__globals__["_markdown_a_html"](
            "<script>alert(1)</script> **texto seguro**"
        )
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("<b>texto seguro</b>", rendered)


if __name__ == "__main__":
    unittest.main()

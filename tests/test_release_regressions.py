import contextlib
import io
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

import agent_google
import agent_notas
import ai_provider_manager


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


if __name__ == "__main__":
    unittest.main()

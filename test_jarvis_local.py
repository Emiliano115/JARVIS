import os
import tempfile
import unittest

import agent_notas


class _Signal:
    def emit(self, *args):
        pass


class _Bridge:
    append_html = _Signal()
    scroll_down = _Signal()


class JarvisLocalFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="jarvis_test_")
        agent_notas._DB_FILE = os.path.join(self.temp_dir.name, "test.db")
        agent_notas._ctx = {
            "base_path": self.temp_dir.name,
            "html_burbuja": lambda html: html,
            "bridge": _Bridge(),
            "hablar": lambda *args: None,
            "memoria_usuario": {},
            "ejecutar_accion": lambda *args: None,
        }
        agent_notas._init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_recordatorio_se_guarda_sin_internet(self):
        agent_notas.recordatorio_crear("tomar agua", minutos=1)
        with agent_notas._get_conn() as conn:
            row = conn.execute(
                "SELECT texto, completado FROM recordatorios"
            ).fetchone()
        self.assertEqual(row["texto"], "tomar agua")
        self.assertEqual(row["completado"], 0)

    def test_memoria_se_categoriza_y_puede_borrarse(self):
        agent_notas.memoria_guardar("ciudad", "Bogota", "preferencias", "prueba")
        with agent_notas._get_conn() as conn:
            row = conn.execute(
                "SELECT categoria, origen FROM memoria_sesion WHERE clave='ciudad'"
            ).fetchone()
        self.assertEqual(tuple(row), ("preferencias", "prueba"))
        agent_notas.memoria_olvidar("ciudad")
        with agent_notas._get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memoria_sesion").fetchone()[0], 0)

    def test_rutina_registra_acciones(self):
        agent_notas.rutina_crear(
            "estudio",
            [{"accion": "abrir_app", "params": {"nombre": "notepad"}}],
        )
        agent_notas.rutina_ejecutar("estudio")
        with agent_notas._get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM rutinas").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM rutinas_log").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
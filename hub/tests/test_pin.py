"""Testes do código (PIN) das apps pessoais (Hub.digito).

Correr (na pasta hub):  python -m unittest discover -s tests
Usam uma app falsa com o código 1234, em vez das do apps.json: não arrancam nada. Só biblioteca standard.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hub   # noqa: E402


class TestPin(unittest.TestCase):
    def setUp(self):
        self.h = hub.Hub()
        self.h.folhas = {"cofre": {"id": "cofre", "nome": "Cofre", "pin": "1234"}}   # sem "saude": abre logo
        self.h.abrir("cofre")

    def marcar(self, codigo):
        for d in codigo:
            self.h.digito(d)

    def test_codigo_certo_abre(self):
        self.marcar("1234")
        limite = time.time() + 2   # o arranque corre numa thread
        while self.h.modo != "app" and time.time() < limite:
            time.sleep(0.01)
        self.assertEqual(self.h.modo, "app")

    def test_cinco_errados_bloqueiam_um_minuto_e_depois_cinco(self):
        self.marcar("0000" * 5)
        self.assertAlmostEqual(self.h.bloqueado_ate - time.time(), 60, delta=2)
        self.marcar("1234")   # bloqueado: nem o certo entra
        self.assertEqual(self.h.modo, "pin")
        self.h.bloqueado_ate = 0   # passou o minuto
        self.marcar("0000" * 5)
        self.assertAlmostEqual(self.h.bloqueado_ate - time.time(), 5 * 60, delta=2)

    def test_codigo_certo_volta_ao_bloqueio_de_um_minuto(self):
        self.marcar("0000" * 5)
        self.h.bloqueado_ate = 0
        self.marcar("1234")
        self.h.fechar()
        self.h.abrir("cofre")
        self.marcar("0000" * 5)
        self.assertAlmostEqual(self.h.bloqueado_ate - time.time(), 60, delta=2)


if __name__ == "__main__":
    unittest.main()

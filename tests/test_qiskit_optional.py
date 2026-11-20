import importlib.util
import os
import unittest
from quantum.iching.verification import check_statevector_line, check_full_register_sampled

@unittest.skipUnless(importlib.util.find_spec('qiskit'), 'Qiskit not installed')
class TestQiskitCircuit(unittest.TestCase):
    def test_all_line_basis_states(self):
        self.assertTrue(check_statevector_line())

    def test_full_24_qubit_sampled_consistency(self):
        self.assertTrue(check_full_register_sampled())

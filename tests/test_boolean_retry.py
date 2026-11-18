"""Dependency-isolated tests for the FreeCAD validator's Boolean retry path."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

VALIDATOR = Path(__file__).resolve().parents[1] / 'integrations' / 'validate_v4_r2.py'

class Vector:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z
    def __sub__(self, other):
        return Vector(self.x-other.x, self.y-other.y, self.z-other.z)
    @property
    def Length(self):
        return (self.x**2 + self.y**2 + self.z**2)**0.5

class Edge:
    def __init__(self, p0, p1):
        self.Vertexes = [types.SimpleNamespace(Point=p0), types.SimpleNamespace(Point=p1)]
        self.Length = (p1-p0).Length

class LineSegment:
    def __init__(self, p0, p1):
        self.edge = Edge(p0,p1)
    def toShape(self):
        return self.edge

class FakeSolid:
    def __init__(self, fail_count):
        self.fail_count = fail_count
        self.calls = 0
    def common(self, edge):
        self.calls += 1
        if self.calls <= self.fail_count:
            raise ValueError('Null shape')
        return types.SimpleNamespace(Edges=[edge])

class BooleanRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(sys.modules, {'FreeCAD':types.SimpleNamespace(Vector=Vector),
                                      'Part':types.SimpleNamespace(LineSegment=LineSegment)}):
            spec=importlib.util.spec_from_file_location('validator_retry_isolated',VALIDATOR)
            cls.validator=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.validator)
    def setUp(self):
        self.validator._boolean_retry_count=0
        self.a, self.b=Vector(0,0,0), Vector(0,0,5)
    def test_no_retry(self):
        solid=FakeSolid(0)
        length,_=self.validator._chord(solid,self.a,self.b)
        self.assertEqual((length,solid.calls,self.validator._boolean_retry_count),(5,1,0))
    def test_one_transient_failure(self):
        solid=FakeSolid(1)
        length,_=self.validator._chord(solid,self.a,self.b)
        self.assertEqual((length,solid.calls,self.validator._boolean_retry_count),(5,2,1))
    def test_persistent_failure_raises(self):
        solid=FakeSolid(3)
        with self.assertRaisesRegex(ValueError,'Null shape'):
            self.validator._chord(solid,self.a,self.b)
        self.assertEqual((solid.calls,self.validator._boolean_retry_count),(3,2))
    def test_other_value_error_not_retried(self):
        class OtherFailure:
            calls=0
            def common(self, edge):
                self.calls+=1
                raise ValueError('Invalid topology')
        solid=OtherFailure()
        with self.assertRaisesRegex(ValueError,'Invalid topology'):
            self.validator._chord(solid,self.a,self.b)
        self.assertEqual((solid.calls,self.validator._boolean_retry_count),(1,0))

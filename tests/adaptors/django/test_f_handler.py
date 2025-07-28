import unittest
from unittest.mock import Mock, patch
from django.db.models import F, Value
from django.db.models.functions import Abs, Round, Floor, Ceil, Greatest, Least
from django.db.models.expressions import Combinable

from statezero.adaptors.django.f_handler import FExpressionHandler

class FExpressionHandlerTests(unittest.TestCase):
    
    def test_simple_field_reference(self):
        """Test processing a simple field reference (SymbolNode)"""
        # This matches the "price" expression test
        expr_obj = {
            "__f_expr": True,
            "original_expr": "price",
            "ast": {
                "mathjs": "SymbolNode",
                "name": "price"
            }
        }
        
        result = FExpressionHandler.process_expression(expr_obj)
        self.assertIsInstance(result, F)
        self.assertEqual(result.name, "price")
    
    def test_constant_value(self):
        """Test processing a constant value (ConstantNode)"""
        # This matches the "42" expression test
        expr_obj = {
            "__f_expr": True,
            "original_expr": "42",
            "ast": {
                "mathjs": "ConstantNode",
                "value": 42
            }
        }
        
        result = FExpressionHandler.process_expression(expr_obj)
        self.assertIsInstance(result, Value)
        self.assertEqual(result.value, 42)
    
    def test_simple_operation(self):
        """Test processing a simple operation (OperatorNode)"""
        # This matches the "price + 10" expression test
        expr_obj = {
            "__f_expr": True,
            "original_expr": "price + 10",
            "ast": {
                "mathjs": "OperatorNode",
                "op": "+",
                "fn": "add",
                "args": [
                    {
                        "mathjs": "SymbolNode",
                        "name": "price"
                    },
                    {
                        "mathjs": "ConstantNode",
                        "value": 10
                    }
                ],
                "implicit": False,
                "isPercentage": False
            }
        }
        
        with patch.object(FExpressionHandler, '_apply_operation') as mock_apply:
            mock_apply.return_value = "processed_operation"
            result = FExpressionHandler.process_expression(expr_obj)
            
            # Verify _apply_operation was called with the correct arguments
            mock_apply.assert_called_once()
            args = mock_apply.call_args[0]
            self.assertEqual(args[0], "+")
            self.assertIsInstance(args[1], F)
            self.assertEqual(args[1].name, "price")
            self.assertIsInstance(args[2], Value)
            self.assertEqual(args[2].value, 10)
    
    def test_function_call(self):
        """Test processing a function call (FunctionNode)"""
        # This matches the "abs(price)" expression test
        expr_obj = {
            "__f_expr": True,
            "original_expr": "abs(price)",
            "ast": {
                "mathjs": "FunctionNode",
                "fn": {
                    "mathjs": "SymbolNode",
                    "name": "abs"
                },
                "args": [
                    {
                        "mathjs": "SymbolNode",
                        "name": "price"
                    }
                ]
            }
        }
        
        with patch.object(FExpressionHandler, '_apply_function') as mock_apply:
            mock_apply.return_value = "processed_function"
            result = FExpressionHandler.process_expression(expr_obj)
            
            # Verify _apply_function was called with the correct arguments
            mock_apply.assert_called_once()
            args = mock_apply.call_args[0]
            self.assertEqual(args[0], "abs")
            self.assertEqual(len(args[1]), 1)
            self.assertIsInstance(args[1][0], F)
            self.assertEqual(args[1][0].name, "price")
    
    def test_nested_expressions(self):
        """Test processing nested expressions with parentheses"""
        # This matches the "(price * 0.9) + (tax * 1.05)" expression test
        expr_obj = {
            "__f_expr": True,
            "original_expr": "(price * 0.9) + (tax * 1.05)",
            "ast": {
                "mathjs": "OperatorNode",
                "op": "+",
                "fn": "add",
                "args": [
                    {
                        "mathjs": "ParenthesisNode",
                        "content": {
                            "mathjs": "OperatorNode",
                            "op": "*",
                            "fn": "multiply",
                            "args": [
                                {
                                    "mathjs": "SymbolNode",
                                    "name": "price"
                                },
                                {
                                    "mathjs": "ConstantNode",
                                    "value": 0.9
                                }
                            ],
                            "implicit": False,
                            "isPercentage": False
                        }
                    },
                    {
                        "mathjs": "ParenthesisNode",
                        "content": {
                            "mathjs": "OperatorNode",
                            "op": "*",
                            "fn": "multiply",
                            "args": [
                                {
                                    "mathjs": "SymbolNode",
                                    "name": "tax"
                                },
                                {
                                    "mathjs": "ConstantNode",
                                    "value": 1.05
                                }
                            ],
                            "implicit": False,
                            "isPercentage": False
                        }
                    }
                ],
                "implicit": False,
                "isPercentage": False
            }
        }
        
        with patch.object(FExpressionHandler, '_apply_operation') as mock_apply:
            # Setup the mock to handle nested calls
            def side_effect(*args):
                if args[0] == "+":
                    return "addition_result"
                elif args[0] == "*":
                    if args[1].name == "price":
                        return "price_mult_result"
                    elif args[1].name == "tax":
                        return "tax_mult_result"
            
            mock_apply.side_effect = side_effect
            result = FExpressionHandler.process_expression(expr_obj)
            
            # Verify _apply_operation was called for both the multiplication operations and the addition
            self.assertEqual(mock_apply.call_count, 3)
    
    def test_complex_function_nesting(self):
        """Test processing complex nested functions"""
        # This matches the "round(min(price * 0.9, cost) + max(tax, 0))" expression test
        expr_obj = {
            "__f_expr": True,
            "original_expr": "round(min(price * 0.9, cost) + max(tax, 0))",
            "ast": {
                "mathjs": "FunctionNode",
                "fn": {
                    "mathjs": "SymbolNode",
                    "name": "round"
                },
                "args": [
                    {
                        "mathjs": "OperatorNode",
                        "op": "+",
                        "fn": "add",
                        "args": [
                            {
                                "mathjs": "FunctionNode",
                                "fn": {
                                    "mathjs": "SymbolNode",
                                    "name": "min"
                                },
                                "args": [
                                    {
                                        "mathjs": "OperatorNode",
                                        "op": "*",
                                        "fn": "multiply",
                                        "args": [
                                            {
                                                "mathjs": "SymbolNode",
                                                "name": "price"
                                            },
                                            {
                                                "mathjs": "ConstantNode",
                                                "value": 0.9
                                            }
                                        ],
                                        "implicit": False,
                                        "isPercentage": False
                                    },
                                    {
                                        "mathjs": "SymbolNode",
                                        "name": "cost"
                                    }
                                ]
                            },
                            {
                                "mathjs": "FunctionNode",
                                "fn": {
                                    "mathjs": "SymbolNode",
                                    "name": "max"
                                },
                                "args": [
                                    {
                                        "mathjs": "SymbolNode",
                                        "name": "tax"
                                    },
                                    {
                                        "mathjs": "ConstantNode",
                                        "value": 0
                                    }
                                ]
                            }
                        ],
                        "implicit": False,
                        "isPercentage": False
                    }
                ]
            }
        }
        
        # Using a simplified approach to test the complex nesting works
        with patch.object(FExpressionHandler, '_process_mathjs_node', wraps=FExpressionHandler._process_mathjs_node) as mock_process:
            with patch.object(FExpressionHandler, '_apply_function') as mock_apply_func:
                with patch.object(FExpressionHandler, '_apply_operation') as mock_apply_op:
                    # Set up minimal mocked returns to allow processing to continue
                    mock_apply_func.return_value = Mock(spec=Combinable)
                    mock_apply_op.return_value = Mock(spec=Combinable)
                    
                    # Process the expression
                    result = FExpressionHandler.process_expression(expr_obj)
                    
                    # Verify that the important nodes were processed correctly
                    expected_function_calls = [
                        "round", "min", "max"
                    ]
                    
                    expected_operation_calls = [
                        "*", "+"  # These should be the operations processed
                    ]
                    
                    actual_function_calls = [
                        call[0][0] for call in mock_apply_func.call_args_list
                    ]
                    
                    actual_operation_calls = [
                        call[0][0] for call in mock_apply_op.call_args_list
                    ]
                    
                    # Check that all expected functions were called
                    for func_name in expected_function_calls:
                        self.assertIn(func_name, actual_function_calls, 
                                     f"Function {func_name} was not processed")
                    
                    # Check that all expected operations were called
                    for op in expected_operation_calls:
                        self.assertIn(op, actual_operation_calls,
                                     f"Operation {op} was not processed")
    
    def test_apply_functions(self):
        """Test that functions are applied correctly"""
        # Test abs function
        f_field = F('price')
        abs_result = FExpressionHandler._apply_function('abs', [f_field])
        self.assertIsInstance(abs_result, Abs)
        
        # Test round function
        round_result = FExpressionHandler._apply_function('round', [f_field])
        self.assertIsInstance(round_result, Round)
        
        # Test min function with two arguments
        min_result = FExpressionHandler._apply_function('min', [f_field, F('cost')])
        self.assertIsInstance(min_result, Least)  # Django uses Least for min
        
        # Test max function with two arguments
        max_result = FExpressionHandler._apply_function('max', [f_field, F('cost')])
        self.assertIsInstance(max_result, Greatest)  # Django uses Greatest for max
    
    def test_apply_operations(self):
        """Test that operations are applied correctly"""
        f_field = F('price')
        value_10 = Value(10)
        
        # Test addition
        add_result = FExpressionHandler._apply_operation('+', f_field, value_10)
        # This should be a direct expression, not wrapped
        self.assertNotEqual(str(add_result), str(f_field))
        
        # Test subtraction
        sub_result = FExpressionHandler._apply_operation('-', f_field, value_10)
        # This should be a direct expression, not wrapped
        self.assertNotEqual(str(sub_result), str(f_field))
        
        # Test multiplication (should be wrapped)
        mult_result = FExpressionHandler._apply_operation('*', f_field, value_10)
        # Should be wrapped in ExpressionWrapper
        self.assertNotEqual(str(mult_result), str(f_field))
        
        # Test invalid operator
        with self.assertRaises(ValueError):
            FExpressionHandler._apply_operation('invalid', f_field, value_10)
    
    def test_non_f_expression_returns_unchanged(self):
        """Test that non-F expressions are returned unchanged"""
        original = {"not": "an_f_expression"}
        result = FExpressionHandler.process_expression(original)
        self.assertEqual(result, original)
        
        # Test with None
        self.assertIsNone(FExpressionHandler.process_expression(None))
        
        # Test with a string
        test_str = "just a string"
        self.assertEqual(FExpressionHandler.process_expression(test_str), test_str)

if __name__ == '__main__':
    unittest.main()
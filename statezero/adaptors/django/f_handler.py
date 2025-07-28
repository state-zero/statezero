import logging
from typing import Any, Dict, List, Set
from django.db.models import F, Value, ExpressionWrapper, IntegerField, FloatField
from django.db.models.expressions import Combinable
from django.db.models.functions import Abs, Round, Floor, Ceil, Greatest, Least

logger = logging.getLogger(__name__)

class FExpressionHandler:
    """
    Handles F expressions from the frontend, converting math.js AST to Django ORM expressions.
    This handler processes the JSON representation of math.js expressions.
    Includes field extraction for permission validation.
    """
    
    # Define allowed functions and their mappings to Django functions
    ALLOWED_FUNCTIONS = {
        'abs': Abs,
        'round': Round,
        'floor': Floor,
        'ceil': Ceil,
        'min': Least,
        'max': Greatest
    }
    
    @staticmethod
    def process_expression(expr_obj: Dict[str, Any]) -> Any:
        """
        Process a structured F expression object into a Django ORM expression.
        
        Args:
            expr_obj: The F expression object from the frontend
            
        Returns:
            A Django ORM expression
        
        Raises:
            ValueError: If the expression is invalid
        """
        if not expr_obj or not isinstance(expr_obj, dict):
            return expr_obj
            
        # Check if it's an F expression
        if expr_obj.get('__f_expr') and 'ast' in expr_obj:
            try:
                # Process the AST from math.js JSON representation
                ast = expr_obj['ast']
                return FExpressionHandler._process_mathjs_node(ast)
            except Exception as e:
                # Log the error for debugging
                logger.error(f"Error processing F expression: {e}")
                raise ValueError(f"Error in F expression: {e}")
            
        return expr_obj
    
    @staticmethod
    def extract_referenced_fields(expr_obj: Dict[str, Any]) -> Set[str]:
        """
        Extract all field names referenced in an F expression.
        
        Args:
            expr_obj: The F expression object from the frontend
            
        Returns:
            Set[str]: Set of field names referenced in the expression
        """
        if not expr_obj or not isinstance(expr_obj, dict):
            return set()
            
        # Check if it's an F expression
        if expr_obj.get('__f_expr') and 'ast' in expr_obj:
            try:
                # Extract field names from the AST
                ast = expr_obj['ast']
                return FExpressionHandler._extract_fields_from_node(ast)
            except Exception as e:
                logger.error(f"Error extracting fields from F expression: {e}")
                return set()
                
        return set()
    
    @staticmethod
    def _extract_fields_from_node(node: Dict[str, Any]) -> Set[str]:
        """
        Recursively extract field names from a math.js AST node.
        
        Args:
            node: Math.js AST node in JSON format
            
        Returns:
            Set[str]: Set of field names referenced in the node
        """
        if not node or not isinstance(node, dict):
            return set()
            
        field_names = set()
        node_type = node.get('mathjs')
        
        if not node_type:
            return field_names
        
        # SymbolNode - field reference
        if node_type == 'SymbolNode':
            field_name = node.get('name')
            if field_name:
                field_names.add(field_name)
                
        # OperatorNode - binary operation
        elif node_type == 'OperatorNode':            
            args = node.get('args', [])
            for arg in args:
                field_names.update(FExpressionHandler._extract_fields_from_node(arg))
                
        # FunctionNode - function call
        elif node_type == 'FunctionNode':
            args = node.get('args', [])
            for arg in args:
                field_names.update(FExpressionHandler._extract_fields_from_node(arg))
                
        # ParenthesisNode - parentheses (just process the content)
        elif node_type == 'ParenthesisNode':
            if 'content' in node:
                field_names.update(FExpressionHandler._extract_fields_from_node(node.get('content')))
                
        return field_names
    
    @staticmethod
    def _process_mathjs_node(node: Dict[str, Any]) -> Any:
        """
        Process a node from the math.js JSON representation
        
        Args:
            node: Math.js AST node in JSON format
            
        Returns:
            Django ORM expression
        
        Raises:
            ValueError: If the node type is unsupported
        """
        if not node or not isinstance(node, dict):
            raise ValueError(f"Invalid node format: {node}")
            
        node_type = node.get('mathjs')  # Math.js consistently uses 'mathjs' as the type field in JSON
            
        if not node_type:
            raise ValueError(f"Missing node type in: {node}")
        
        # SymbolNode - field reference
        if node_type == 'SymbolNode':
            field_name = node.get('name')
            if not field_name:
                raise ValueError("Field name is required")
                
            # Basic validation for field name format
            if not all(c.isalnum() or c == '_' for c in field_name):
                raise ValueError(f"Invalid field name: {field_name}")
                
            return F(field_name)
            
        # ConstantNode - literal value
        elif node_type == 'ConstantNode':
            if 'value' not in node:
                raise ValueError("Value node is missing the 'value' property")
                
            value = node.get('value')
            return Value(value)
            
        # OperatorNode - binary operation
        elif node_type == 'OperatorNode':
            operator = node.get('op')
            
            args = node.get('args', [])
            if len(args) != 2:  # Ensure binary operation
                raise ValueError(f"Expected 2 arguments for operator {operator}, got {len(args)}")
                
            left = FExpressionHandler._process_mathjs_node(args[0])
            right = FExpressionHandler._process_mathjs_node(args[1])
            
            return FExpressionHandler._apply_operation(operator, left, right)
            
        # FunctionNode - function call
        elif node_type == 'FunctionNode':
            # Extract function name from the nested fn object, which is a SymbolNode
            if 'fn' in node and isinstance(node['fn'], dict):
                fn_node = node['fn']
                if fn_node.get('mathjs') == 'SymbolNode':
                    func_name = fn_node.get('name')
                else:
                    raise ValueError(f"Unsupported function node structure: {fn_node}")
            else:
                raise ValueError("Function node missing required 'fn' property")
            
            if not func_name:
                raise ValueError("Function name not found in function node")
            
            # Check if function is allowed
            if func_name not in FExpressionHandler.ALLOWED_FUNCTIONS:
                raise ValueError(f"Unsupported function: {func_name}")
                
            args = node.get('args', [])
            if not args:
                raise ValueError(f"Function {func_name} requires at least one argument")
                
            processed_args = [FExpressionHandler._process_mathjs_node(arg) for arg in args]
            
            return FExpressionHandler._apply_function(func_name, processed_args)
            
        # ParenthesisNode - parentheses (just process the content)
        elif node_type == 'ParenthesisNode':
            if 'content' not in node:
                raise ValueError("ParenthesisNode missing 'content'")
                
            return FExpressionHandler._process_mathjs_node(node.get('content'))
            
        # Other node types - not supported
        else:
            raise ValueError(f"Unsupported node type: {node_type}")
    
    @staticmethod
    def _apply_operation(operator: str, left: Any, right: Any) -> Combinable:
        """
        Apply a binary operation with proper output field handling
        
        Args:
            operator: Operation type
            left: Left operand
            right: Right operand
            
        Returns:
            Django expression result
        
        Raises:
            ValueError: If the operation is unsupported
        """
        # Apply the operation based on the operator
        if operator == '+':
            expression = left + right
            # Addition between two fields might need output type specification
            if isinstance(left, F) and isinstance(right, F):
                return ExpressionWrapper(expression, output_field=FloatField())
            return expression
            
        elif operator == '-':
            expression = left - right
            # Subtraction between two fields might need output type specification
            if isinstance(left, F) and isinstance(right, F):
                return ExpressionWrapper(expression, output_field=FloatField())
            return expression
            
        elif operator == '*':
            expression = left * right
            # Multiplication might need float output field
            return ExpressionWrapper(expression, output_field=FloatField())
            
        elif operator == '/':
            # Division always needs float output field
            expression = left / right
            return ExpressionWrapper(expression, output_field=FloatField())
            
        elif operator == '%':
            expression = left % right
            return ExpressionWrapper(expression, output_field=IntegerField())
            
        elif operator == '^':
            # Power operation requires special handling
            if isinstance(right, Value):
                output_field = IntegerField() if isinstance(right.value, int) and right.value >= 0 else FloatField()
                return ExpressionWrapper(left ** right.value, output_field=output_field)
            else:
                raise ValueError("Power operations require a constant right operand")
                
        else:
            # This shouldn't happen due to earlier validation
            raise ValueError(f"Unsupported operator: {operator}")
    
    @staticmethod
    def _apply_function(func_name: str, args: List[Any]) -> Combinable:
        """
        Apply a function with proper output field handling
        
        Args:
            func_name: Function name
            args: Function arguments
            
        Returns:
            Django function expression
        
        Raises:
            ValueError: If the function is unsupported
        """
        # Get the Django function class
        func_class = FExpressionHandler.ALLOWED_FUNCTIONS.get(func_name)
        if not func_class:
            raise ValueError(f"Unsupported function: {func_name}")
            
        # Apply function with appropriate output field
        if func_name in ('abs', 'round', 'floor', 'ceil'):
            # These functions preserve the input type
            if len(args) != 1:
                raise ValueError(f"Function {func_name} takes exactly 1 argument")
            return func_class(args[0])
            
        elif func_name in ('min', 'max'):
            # These functions need at least 2 arguments
            if len(args) < 2:
                raise ValueError(f"Function {func_name} requires at least 2 arguments")
            return func_class(*args)
            
        else:
            # This shouldn't happen due to earlier validation
            raise ValueError(f"Function {func_name} implementation missing")
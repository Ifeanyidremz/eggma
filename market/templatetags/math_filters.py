from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()

@register.filter
def div(value, divisor):
    """Divide value by divisor"""
    try:
        if divisor == 0:
            return 0
        return float(value) / float(divisor)
    except (ValueError, TypeError, InvalidOperation):
        return 0

@register.filter  
def mul(value, multiplier):
    """Multiply value by multiplier"""
    try:
        return float(value) * float(multiplier)
    except (ValueError, TypeError, InvalidOperation):
        return 0

@register.filter
def percentage(value, total):
    """Calculate percentage: (value / total) * 100"""
    try:
        if total == 0:
            return 50.0  # Default fallback
        return (float(value) / float(total)) * 100
    except (ValueError, TypeError, InvalidOperation):
        return 50.0

@register.filter
def sub(value, subtractor):
    """Subtract subtractor from value"""
    try:
        return float(value) - float(subtractor)
    except (ValueError, TypeError, InvalidOperation):
        return 0

@register.filter
def add_decimal(value, addend):
    """Add two decimal values"""
    try:
        return float(value) + float(addend)
    except (ValueError, TypeError, InvalidOperation):
        return 0
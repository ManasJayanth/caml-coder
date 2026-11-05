"""Smoke subject: a 20-line file for provider transport verification. Not production code."""
def add(a, b):
    return a + b


def sub(a, b):
    return a - b


def mul(a, b):
    return a * b


def div(a, b):
    if b == 0:
        raise ZeroDivisionError('b must be nonzero')
    return a / b


if __name__ == '__main__':
    print(add(1, 2), sub(5, 3), mul(2, 4), div(8, 2))

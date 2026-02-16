"""Bot — модуль автоматизации прохождения тестов."""

from bot.auth import AuthManager
from bot.browser import BrowserManager
from bot.test_solver import TestSolver

__all__ = ["AuthManager", "BrowserManager", "TestSolver"]

# Global conftest - patch _ (gettext) for all tests
import builtins

builtins._ = lambda s: s

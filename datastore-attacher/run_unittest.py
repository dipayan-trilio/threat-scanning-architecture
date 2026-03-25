#!/usr/bin/env python3
"""
Test runner for targetPoller unit tests using unittest.

Alternative to pytest for running tests without additional dependencies.

Usage:
    python run_unittest.py                      # Run all tests
    python run_unittest.py test_cleanup         # Run specific test module
    python run_unittest.py TestCleanupBasicLogic # Run specific test class
"""

import sys
import os
import unittest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_all_tests():
    """Run all unit tests in targetPoller/tests/"""
    loader = unittest.TestLoader()
    start_dir = 'targetPoller/tests'
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1

def run_specific_test(test_name):
    """Run specific test module or class"""
    loader = unittest.TestLoader()
    
    # Try loading as module first
    try:
        module_path = f'targetPoller.tests.{test_name}'
        suite = loader.loadTestsFromName(module_path)
    except (ImportError, AttributeError):
        # Try as test class
        try:
            suite = loader.loadTestsFromName(test_name)
        except Exception as e:
            print(f"Error: Could not find test '{test_name}'")
            print(f"Details: {str(e)}")
            return 1
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1

def main():
    """Main entry point"""
    print("=" * 80)
    print("  TargetPoller Unit Tests (unittest)")
    print("=" * 80)
    print()
    
    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        print(f"Running specific test: {test_name}")
        print()
        exit_code = run_specific_test(test_name)
    else:
        print("Running all tests...")
        print()
        exit_code = run_all_tests()
    
    print()
    if exit_code == 0:
        print("=" * 80)
        print("  All tests passed! ✓")
        print("=" * 80)
    else:
        print("=" * 80)
        print("  Some tests failed ✗")
        print("=" * 80)
    
    return exit_code

if __name__ == '__main__':
    sys.exit(main())

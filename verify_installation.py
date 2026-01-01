#!/usr/bin/env python3
"""
Installation verification script for FACTRADE RAG System.
Run this to verify your installation is correct.
"""

import sys
from pathlib import Path

def check_python_version():
    """Check Python version."""
    print("Checking Python version...")
    version = sys.version_info
    if version.major == 3 and version.minor >= 9:
        print(f"✓ Python {version.major}.{version.minor}.{version.micro} (OK)")
        return True
    else:
        print(f"✗ Python {version.major}.{version.minor}.{version.micro} (FAILED)")
        print("  Python 3.9 or higher is required")
        return False

def check_dependencies():
    """Check if required dependencies are installed."""
    print("\nChecking dependencies...")
    
    required = [
        'langchain',
        'langchain_community',
        'langchain_openai',
        'openai',
        'chromadb',
        'fastapi',
        'pydantic',
        'structlog',
        'watchdog',
        'pytest',
    ]
    
    missing = []
    for package in required:
        try:
            __import__(package)
            print(f"✓ {package}")
        except ImportError:
            print(f"✗ {package} (MISSING)")
            missing.append(package)
    
    if missing:
        print(f"\nMissing packages: {', '.join(missing)}")
        print("Install with: pip install -r requirements.txt")
        return False
    
    return True

def check_environment():
    """Check environment variables."""
    print("\nChecking environment variables...")
    import os
    
    if 'OPENAI_API_KEY' in os.environ:
        key = os.environ['OPENAI_API_KEY']
        if key.startswith('sk-'):
            print(f"✓ OPENAI_API_KEY is set")
            return True
        else:
            print(f"✗ OPENAI_API_KEY appears invalid (should start with 'sk-')")
            return False
    else:
        print(f"✗ OPENAI_API_KEY not set")
        print("  Set with: export OPENAI_API_KEY='sk-your-key-here'")
        return False

def check_file_structure():
    """Check if required files exist."""
    print("\nChecking file structure...")
    
    required_files = [
        'config.yaml',
        'requirements.txt',
        'main.py',
        'src/__init__.py',
        'src/rag_system.py',
        'src/config_manager.py',
        'src/integrity_checker.py',
        'src/quality_checker.py',
        'src/auto_debugger.py',
        'src/auto_updater.py',
        'src/logger.py',
        'src/api.py',
    ]
    
    missing = []
    for filepath in required_files:
        if Path(filepath).exists():
            print(f"✓ {filepath}")
        else:
            print(f"✗ {filepath} (MISSING)")
            missing.append(filepath)
    
    if missing:
        print(f"\nMissing files: {', '.join(missing)}")
        return False
    
    return True

def check_directories():
    """Check if required directories exist."""
    print("\nChecking directories...")
    
    required_dirs = [
        'src',
        'tests',
        'data/documents',
    ]
    
    for dirpath in required_dirs:
        path = Path(dirpath)
        if path.exists():
            print(f"✓ {dirpath}/")
        else:
            print(f"Creating {dirpath}/...")
            path.mkdir(parents=True, exist_ok=True)
            print(f"✓ {dirpath}/ (CREATED)")
    
    return True

def check_configuration():
    """Check if configuration is valid."""
    print("\nChecking configuration...")
    
    try:
        sys.path.insert(0, '.')
        from src.config_manager import get_config
        
        config = get_config()
        print(f"✓ Configuration loaded successfully")
        print(f"  System: {config.system.name}")
        print(f"  Version: {config.system.version}")
        print(f"  Environment: {config.system.environment}")
        return True
    except Exception as e:
        print(f"✗ Configuration failed to load: {e}")
        return False

def check_imports():
    """Check if all source modules can be imported."""
    print("\nChecking module imports...")
    
    modules = [
        'src.config_manager',
        'src.logger',
        'src.integrity_checker',
        'src.quality_checker',
        'src.auto_debugger',
        'src.auto_updater',
        'src.rag_system',
        'src.api',
    ]
    
    sys.path.insert(0, '.')
    
    failed = []
    for module in modules:
        try:
            __import__(module)
            print(f"✓ {module}")
        except Exception as e:
            print(f"✗ {module}: {e}")
            failed.append(module)
    
    if failed:
        print(f"\nFailed to import: {', '.join(failed)}")
        return False
    
    return True

def main():
    """Run all checks."""
    print("="*60)
    print("FACTRADE RAG System - Installation Verification")
    print("="*60)
    
    checks = [
        ("Python Version", check_python_version),
        ("Dependencies", check_dependencies),
        ("Environment", check_environment),
        ("File Structure", check_file_structure),
        ("Directories", check_directories),
        ("Configuration", check_configuration),
        ("Module Imports", check_imports),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} check failed with error: {e}")
            results.append((name, False))
    
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    
    for name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{name:.<40} {status}")
    
    all_passed = all(result for _, result in results)
    
    print("\n" + "="*60)
    if all_passed:
        print("✓ All checks passed! Installation is complete.")
        print("\nYou can now run:")
        print("  python main.py --mode cli")
        print("  python main.py --mode api")
        return 0
    else:
        print("✗ Some checks failed. Please fix the issues above.")
        return 1

if __name__ == '__main__':
    sys.exit(main())

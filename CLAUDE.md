# **AGENTS.md - Project Coding Standards and Rules**

## **🎯 Core Philosophy**

- **Do what has been asked; nothing more, nothing less**
- **NEVER create files unless absolutely necessary**
- **ALWAYS prefer editing existing files over creating new ones**
- **Ensure planning, design, spec creation all tend towards elegant simple solutions. Avoid overengineering, code bloat, excessively complex solutions at ALL COSTS**
- Work should be bite sized ... the tests should be bite sized ... the verification should be bite sized and the final analysis and reporting should be bite sized. Do not try to take on atomically any task or workitem thats large and can take longer to build, verify and analyse. Always attempt to deconstruct reasonably
- Before committing, review your code changes to ensure that this is a scalable change. This application is to be designed to be able to process large documents, each with thousands of pages, and many thousands of such documents, the total documents size could be in hundreds of GBs- 
- When doing any language related work (exmple - semantic comparison) ensure NO deterministic comparison, NO regex/stopwards/keywards based fallbacks. These are brittle and must be avoided.

## **📏 File Size Rules**

### **File Size Limits**

- **Python files (.py)**: Maximum 350-400 lines
- **JavaScript files (.js)**: Maximum 350-400 lines
- **HTML files (.html)**: Maximum 350-400 lines
- **CSS files (.css)**: Maximum 350-400 lines
- **TypeScript files (.ts/.tsx)**: Maximum 350-400 lines
- **Configuration files**: No strict limit, but keep concise
- **Markdown files: No strict limits** ... they can be bigger in size

### **Function/Method Size Limits**

- **All functions**: Maximum 50-75 lines
- **Class methods**: Maximum 50-75 lines
- **Complex logic**: Break into smaller helper functions
- **Single responsibility**: Each function does ONE thing well

## **🧪 Testing Requirements**

### **No Mock Testing**

- **NEVER use mock data or simulations**
- **ALWAYS test against real systems**
- **NO bypassing actual testing**
- **NO shortcuts or fabricated results**
- **Fail fast. Do not add any fallbacks if now explicitly mentioned in the requirements**

## **🔍 Search and Navigation**

### **Use AST-Grep for Structural Search**

```plaintext
# Syntax-aware search (prefer over grep/rg)
ast-grep --lang python -p 'def $FUNC($$$)'
ast-grep --lang javascript -p 'class $CLASS { $$$ }'
ast-grep --lang ruby -p 'def $METHOD; $$$ end'
```

### **Directory Management**

- **Always use absolute paths**
- **Check current directory with** `**pwd**` **before operations**
- **Stay within project root - NEVER navigate outside**

## **📦 Git Practices**

### **Commit Guidelines**

- **NEVER blindly revert to older commits**
- **Surgically revert specific changes only**
- **Preserve user's interim work**
- **Small, atomic commits**
- **Clear, descriptive commit messages**

## **🚀 Development Workflow**

### **Before Starting**

1. Check current directory: `pwd`
2. Activate virtual environment: `source .venv/bin/activate`. Create one if it is not there.
3. Always do package management with UV. pdate dependencies: `uv pip sync requirements.txt`
4. Check for port conflicts: `lsof -i :PORT`

### **During Development**

1. Write code following size limits
2. Run linting: `ruff check --fix .`
3. Run type checking: `uvx ty .`
4. Compile check: `python -m py_compile file.py`
5. Import check: `python -c "import module"`
6. If Python code changed, run a PyArmor smoke check before commit: `uvx --from pyarmor==8.5.11 pyarmor gen --recursive --output /tmp/pyarmor-check app`
7. Always use `pyproject.toml for dependency management. Never install packages directly. Always install via pyproject.toml
8. Keep dependencies up-to-date and minimal
9. Pin exact versions in production environments
10. Always rerun pyproject based installation to ensure the environment is upto the mark

### **Before Committing**

1. All tests pass
2. Linting clean: `ruff check .`
3. Types valid: `ty .`
4. PyArmor smoke check passes for Python changes: `uvx --from pyarmor==8.5.11 pyarmor gen --recursive --output /tmp/pyarmor-check app`
5. Real system testing complete
6. Documentation updated (if requested)

## **🔴 Critical Rules - NEVER VIOLATE**

1. **NO mock testing** - Real systems only
2. **NO shortcuts** - Full testing required
3. **NO fabricated results** - Authentic data only
4. **NO blind reverts** - Surgical changes only
5. **NO exceeding size limits** - Refactor when needed
6. **NO unnecessary files** - Edit existing when possible
7. **NO unsolicited documentation** - Only when requested
8. **NO working outside project root** - Stay contained
9. **NO bypassing validation** - All checks must pass
10. **NO incomplete features** - Full test coverage required
11. **NO Overengineering, code bloat, overtly complex specs, design or plans**

## **📋 Checklist for Completion**

-  All functions ≤ 75 lines
-  All files ≤ 400 lines
-  Virtual environment active
-  Dependencies installed via uv
-  Ruff linting passes
-  ty type checking passes
-  Python compilation successful
-  All imports working
-  PyArmor smoke check passes for Python changes
-  Real API tests complete
-  cURL tests verified
-  Playwright tests passing
-  Screenshots/videos captured
-  No mock data used
-  No shortcuts taken
-  Edge cases handled
-  Error scenarios tested

## Make sure to refer the appropriate guideline documents for UI implementation/testing -

- @docs/coding-guidelines/frontend-asthetics.md
- @docs/coding-guidelines/HTMX_GUIDELINES.md

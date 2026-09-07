# LLM-Powered AI Coding Assistant

A Python-based AI coding assistant that uses large language models to help with coding tasks through an agent-based workflow.

## Features

- AI-driven coding assistance
- Agent workflow for handling requests
- Modular prompts, tools, states, and graph logic
- Environment-variable support for API credentials
- Python project configuration managed with `pyproject.toml`

## Project Structure

```text
.
├── Agent/
│   ├── app.py          # Application logic
│   ├── graph.py        # Agent workflow graph
│   ├── prompts.py      # Prompts used by the assistant
│   ├── states.py       # Agent state definitions
│   └── tools.py        # Tools available to the agent
├── main.py             # Application entry point
├── pyproject.toml      # Project dependencies and settings
└── README.md
```

## Requirements

- Python 3.10 or newer
- An API key for the LLM provider configured by the project

## Installation

Clone the repository:

```bash
git clone https://github.com/CodePhantom05/LLM-Powered-AI-Coding-Assistant.git
cd LLM-Powered-AI-Coding-Assistant
```

Install dependencies with `uv`:

```bash
uv sync
```

Or, if you use pip:

```bash
pip install -e .
```

## Configuration

Create a `.env` file in the project root and add the API credentials required by the application.

```env
# Add your API credentials here.
# Never commit this file to GitHub.
```

The `.env` file is intentionally excluded from version control to keep credentials private.

## Run the Application

```bash
python main.py
```

## Security

Never upload API keys, passwords, or `.env` files to GitHub. If a key is accidentally exposed, revoke it and create a replacement key immediately.

## License

This project is intended for learning and personal development. Add a license file if you plan to share or distribute it.

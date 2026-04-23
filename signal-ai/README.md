# Signal.AI – The Multi-Agent Tech Reporter

Signal.AI is an advanced, autonomous agent platform designed to act as your personal technology reporter. Leveraging a sophisticated multi-agent architecture orchestrated by **LangGraph**, Signal.AI listens to your voice or text commands, searches the web for the latest tech breakthroughs, summarizes key findings using **local LLMs**, and drafts ready-to-publish updates for your social media platforms.

By integrating human-in-the-loop confirmation, Signal.AI combines the speed of automation with human editorial control.



## Core Capabilities

* **🎙️ Real-time Voice I/O:** Command the agent via microphone (Streaming STT) and receive spoken summaries and updates (TTS).
* **🤖 Multi-Agent Pipeline:** Intention classification, web searching, summarization, and formatting are handled by specialized agents working in concert.
* **💻 Local LLMs via Ollama:** Maintain data privacy and eliminate API costs by running models like `llama3` or `mistral` locally.
* **🔗 Social Media Integration:** Connect and post directly to **LinkedIn**, **Facebook**, and **Twitter (X)** after human review.
* **📊 Live Pipeline Visualization:** Watch the agent move through steps (Classify, Search, Summarize, Format) in real-time.
* **🗄️ Contextual Memory:** Robust session management using **Redis** for quick caching and **MongoDB** for long-term history persistence.

---

## Visual Walkthrough

Here is how you interact with and manage Signal.AI.

### 1. The Workspace

The main dashboard is split into three areas:
* **Left Sidebar:** Manage chat history and toggle **Voice Mode**.
* **Main Chat:** The live interaction viewport and input area.
* **Right Sidebar:** View real-time agent pipeline progress, interaction stats, and recent successful posts.



### 2. Connected Accounts (Settings)

Access the Settings modal via your avatar. Here, you can manually connect or disconnect your social media accounts. Signal.AI uses manual token management for LinkedIn and Facebook, and standard OAuth for Twitter (X).

### 3. Pipeline in Action (Searching & Summarizing)

When you ask for news (e.g., *"latest news about AI"*), the intention is classified. You can see the **Agent Pipeline** on the right move from Standby to Step 2 (**Search Web**) and Step 3 (**Summarize**). The AI streams tokens (words) to the chat as they are generated.



### 4. Human-in-the-Loop Confirmation

Signal.AI will never post destructive actions without your permission. After summarizing and formatting a post based on your connected platforms, the agent pauses the workflow and asks for confirmation.

![Post Confirmation Request](./signal%2004.png)

You can click **Post** to publish, **Cancel** to abort, or simply tell the agent to *"reformat the post"* to try again.

(signa01.png)
(signal02.png)
(signal03.png)
(signal04.png)


---

## Technology Stack

* **Backend:** FastAPI (Async Python)
* **Multi-Agent Orchestration:** LangGraph (LangChain ecosystem)
* **LLM Engine:** Ollama (running local llama3/mistral)
* **Databases:** MongoDB (persistence), Redis (session caching)
* **Voice STT:** Faster Whisper (local)
* **Voice TTS:** MelTTS (local)

## Getting Started

### Prerequisites

You must have the following installed and running locally:

1.  **Python 3.10+**
2.  **Ollama:** Installed and `llama3` (or preferred model) pulled: `ollama pull llama3`
3.  **MongoDB:** Installed and running on standard port `27017`.
4.  **Redis:** Installed and running on standard port `6379`.

### Installation

1.  Clone the repository:
    ```bash
    git clone copy the url and clone
    cd signal-ai
    ```

2.  Create and activate a virtual environment:
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Mac/Linux
    source venv/bin/activate
    ```

3.  Install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```

4.  Configure environment variables:
    Create a `.env` file in the root directory and add necessary keys (if any for search APIs) and configure your model names.

    ```env
    OLLAMA_MODEL=llama3
    MONGODB_URL=mongodb://localhost:27017
    REDIS_URL=redis://localhost:6379
    # Add optional social media client IDs if needed
    ```

### Running the Application

1.  Start the FastAPI backend server:
    ```bash
    # From the project root
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
    ```

2.  Open your browser and navigate to:
    `http://localhost:8000`

Register a new account (or sign in if already registered), connect your social media tokens in Settings, and start commanding your Tech Reporter!

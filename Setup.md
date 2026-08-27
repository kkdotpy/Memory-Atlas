# Project Setup & Environment Guide

This project is developed locally to keep development economically feasible and to account for initial constraints with cloud deployment architectures. While there are plans to transition to a fully cloud-hosted deployment in the future, the application currently runs entirely on local hardware. 

If you wish to run this project on your own machine, set up two core local engines: **Ollama** (for LLM inference) and **ComfyUI** (for image generation workflows). Additionally, running these models locally requires a dedicated GPU, sufficient VRAM/RAM, and adequate internal storage space.


##  Local LLM Environment & Project Setup

For getting the text feedbacks I am using local setup with ollama and 'Mistral:7B' Model. This guide walks through setting up the Ollama Desktop runtime on Windows, pulling the required `mistral:7b` model

###  1. Prerequisites & Engine Installation

1. **Download Ollama for Windows**:
   Download and run the installer from the official page: [https://ollama.com/download/windows](https://ollama.com/download/windows)
2. **Complete Installation**:
   Follow the setup wizard. Once installed, Ollama runs automatically in your Windows system tray and listens on `http://127.0.0.1:11434`.
3. **Verify Installation**:
   Open **PowerShell** or **Command Prompt** and check the installation:
   ```powershell
   ollama --version
   ```
### 2. Model Setup
Since the project uses Mistral:7b, that model should be pulled first.
```powershell
ollama pull mistral:7b
```

Verify that the model downloaded successfully:
```powershell
ollama list
```


## Image Pipeline Setup

For image generation and testing prototype for free, ComfyUI was used for image generation task. For installation of ComfyUI the link is: Link

### About ComfyUI:
ComfyUI is a opensource project which became the professional standard for visual AI. This allows users to access powerful text to image models utilizing their local computational setup.


### Setting Up ComfyUI Integration

1. **Install and Launch ComfyUI:**
   Follow the official [ComfyUI Installation Guide](https://github.com/comfyanonymous/ComfyUI) for your operating system. Launch ComfyUI so it is running locally (default: `http://127.0.0.1:8188`).

2. **Load the Workflow JSON:**
   Open the ComfyUI web UI in your browser. Click **Load** (or drag and drop) the `rt_therapy_workflow.json` file provided in this repository directly onto the canvas.

3. **Verify Models & Test Generation:**
   Ensure all required model files are present in your `ComfyUI/models/` folder. Click **Queue Prompt** inside ComfyUI to verify that the image generation pipeline runs successfully on your hardware.

4. **Run Background Service:**
   Keep ComfyUI running in the background while executing `image_client.py`. The script connects to  ComfyUI's local API to generate images dynamically based on user prompts.

> ### 💡 Alternative: Using Cloud Image APIs (Gemini / Stable Diffusion)
> 
> This project uses a **100% local hardware setup via ComfyUI** to keep generation costs completely free and avoid ongoing subscription or pay-per-use API fees.
> 
> However, if local hardware resources (GPU/VRAM) are limited, or if faster generation speeds are needed without setting up local models, the pipeline can be swapped to use a cloud API:
> 
> **Cloud API Considerations:**
> * **Supported Services:** Providers such as Google Gemini (Imagen 3) or Stability AI (Stable Diffusion API) can be integrated directly into `image_client.py`.
> * **Required Code Changes:**
>   1. Replace the WebSocket/ComfyUI queue logic in `image_client.py` with standard HTTP `POST` requests.
>   2. Add an API Key variable to an `.env` file (e.g., `GEMINI_API_KEY` or `STABILITY_API_KEY`).
>   3. Update dependency requirements to include official SDKs (e.g., `google-genai` or `stability-sdk`).
> * **Trade-offs:** Cloud APIs eliminate local model setup and offer faster generation speeds, but incur pay-per-use costs based on volume.


## 2. Python Environment & Dependencies

1. **Clone/Download Repository**: Ensure all project files are located in your working directory.
2. **Install Dependencies**: Open your terminal or VS Code terminal in the project directory and run:

```bash
pip install -r requirements.txt
```
## 3. Running the Application
Once Ollama is active in your system tray and the dependencies are installed, launch the backend:
```bash
python main.py
```






# Digital Reminiscence Therapy & Visual Journaling System

A local, LLM-driven cognitive stimulation platform designed to support individuals with dementia, reduce caregiver pre-death grief, and strengthen caregiver-patient relationships through personalized visual storybooks and memory-recall games.

---

## 1. Product Overview & Literature Review

### Clinical Background: Reminiscence Therapy (RT)
Reminiscence Therapy has been a foundational approach in cognitive stimulation therapy since the 1980s. While individuals living with dementia often experience significant short-term memory loss, long-term nostalgic memories such as a childhood pet or early life experiences frequently remain accessible. 

RT leverages sensory prompts like music, art, personal stories, and photographs to guide structured conversations. Encouraging a positive perspective on life through nostalgic recall helps stimulate cognitive function and addresses pre-death grief—a common phenomenon involving anticipatory loss experienced by families and caregivers prior to a loved one's passing.

### Key Insights from Literature
* **Cognitive Stimulation**: Talking about nostalgic past events provides meaningful mental exercises, helping preserve long-term narrative identity even when recent events (or immediate family names) become difficult to recall.
* **Grief & Relationship Quality**: Digital tools featuring personalized photos and guided prompts help mitigate caregiver burden and deepen the emotional connection between caregivers and care recipients.
* **Preservation Through Journaling**: Converting spoken memories into structured journals or visual storybooks creates permanent artifacts for continuous reflection and long-term memory preservation.

---

## 2. Product Vision & Core Features

The primary objective of this project is to create an effective, visually rich memory recall system by combining text-based LLMs for conversation/story generation and diffusion models for image synthesis.

* **Guided Conversational Journaling**: Uses an interactive text LLM to assist users in sharing past memories and structuring them into cohesive narratives.
* **Visual Storybook Generation**: Automatically creates contextual illustrations to visually anchor narrative memories into readable digital storybooks.
* **Flashcard Memory Games**: Converts completed storybooks into interactive event-specific quizzes to test and support memory retention in an engaging format.

---

## 3. Usage & Target Audiences

* **Assisted Caregiver Use**: Intended primarily for use alongside a caregiver, family member, or health assistant who can facilitate conversation and guide the patient through the visual prompts.
* **Personal Digital Archiving**: Can also be used independently by individuals or families wishing to record personal histories and preserve memories into digital keepsakes for future generations.

---

## 4. Local Setup & Hardware Prerequisites

Because no cloud-based implementation or web application hosted platform is available yet, running the project currently requires a local setup. 

Setting up the system locally involves installing two main engines (**Ollama** for text generation and **ComfyUI** for image generation), alongside python dependencies and dedicated GPU hardware.

If you are keen to test and run the project locally on your machine, please refer to the setup guide in **`setup.md`**.

---

## 5. References & Academic Sources

* **Dementia Support & Caregiving Services (DSCS)**: *Reminiscence Therapy and Cognitive Stimulation*. [Reference Link](https://www.dscs.hk/en/caregiving-skills/treatments/reminiscence-therapy/index.html)
* **USC Leonard Davis School of Gerontology**: *Digital Reminiscence App Could Reduce Grief and Improve Relationships Between Dementia Patients and Caregivers*. [Reference Link](https://gero.usc.edu/2026/04/22/digital-reminiscence-dementia-caregivers/)
* **Alzheimer's Association**: *Reminiscence and Reminiscence Therapy Guidelines*. [Reference Link](https://www.alz.org/help-support/caregiving/daily-care/reminiscence-and-reminiscence-therapy)
* **Research to Design**: *Sketching a Game to Trigger Reminiscence in Older Adults*. [Reference Link](https://openreview.net/pdf/6e6ffd60b76c1b767584c69eba5b636e7e3adae8.pdf)




<br>

> # Product Objectives

> ### 💡 Core Mission
> To provide an accessible, low-friction digital platform where individuals with dementia can explore and record cherished memories, supported by interactive AI, custom visual storybooks, and real-time caregiver guidance.

---

### 1. User-Led Memory Prompts
* **Open & Flexible Input**: Users can type or speak **any memory prompt** or topic that comes to mind, regardless of how brief or unstructured it is.

---

### 2. Conversational LLM Engine
* **Empathetic & Friendly Tone**: The assistant communicates with warmth, patience, and encouraging language to put the user at ease.
* **Elaboration & Nostalgic Recall**: Rather than giving short answers, the LLM actively asks gentle, follow-up questions to help the user dive deeper into their thoughts and uncover richer details about the past.

---

### 3. Accessible & Non-Intimidating UI Design
* **Senior-Friendly Interface**: The user interface avoids harsh contrast, overwhelming options, or bright, intimidating color palettes.
* **Calming Visual Ergonomics**: Designed specifically to reduce cognitive load and visual fatigue for older adults and individuals with cognitive impairments.

---

### 4. Automated Memory Storybook Generation
* **Permanent Story Formatting**: Once a chatting session concludes and the memory is "sealed," the application automatically compiles the conversation into a structured, narrative storybook.
* **Visual Anchor Integration**: Includes AI-generated illustrations created during the chat to visually represent the memory.
* **Long-Term Revisitability**: Storybooks are saved permanently so patients, families, and caregivers can return to and read through them repeatedly to reinforce cognitive stimulation over time.

---

### 5. Dynamic Caregiver Assistance Window

> 🧠 **Caregiver Context Window**  
> *After every response from the LLM assistant, a dedicated, real-time context panel updates automatically with targeted question prompts and conversational cues.*  
> 
> * **Purpose**: Serves as a live cheat-sheet for caregivers or family members sitting alongside the patient, helping them ask meaningful, context-specific follow-up questions to encourage further dialogue.


> SNAPSHOTS of the interface
> <img width="1920" height="1080" alt="Outlook of the App" src="https://github.com/user-attachments/assets/fd8cb02c-b7d9-4f85-a816-03f35e02b273" />
> <img width="1920" height="1080" alt="Left Pane" src="https://github.com/user-attachments/assets/b87a8ce8-3349-42c2-a51d-1f9dff9385e7" />
> <img width="1920" height="1080" alt="Main body" src="https://github.com/user-attachments/assets/44ab53fc-f926-4af9-8218-8aba513d3c3b" />
> <img width="1920" height="1080" alt="Right Pane" src="https://github.com/user-attachments/assets/f1e35ed3-f84d-475d-b78f-5e2a380f3ac5" />




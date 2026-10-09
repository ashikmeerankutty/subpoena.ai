# Project Specification: Subpoena.ai 

**Tagline:** The API-First Multi-Agent Fraud Defense Engine that Calls the User as a Witness  
**Category Track:** BFSI: Intelligent Risk & Fraud / Agentic Workflows  
**Target Event:** Google Cloud AI Builder Cup  

---

## 1. Executive Summary & Problem Statement

### The Problem
Traditional fraud detection relies on black-box ML classifiers that produce a single confidence score, leading to two critical failures for enterprise banking:
1. **High False Positive Rates (FPR):** Legitimate users making anomalous purchases are hard-blocked, causing customer churn.
2. **The "Explainability Crisis":** Analysts spend hours correlating disparate logs because traditional models cannot explain their reasoning.

### The API-First Solution: Subpoena.ai
**Subpoena.ai** is a headless, API-first fraud resolution engine powered by **Multi-Agent Debate (MAD)** and **Adaptive Conversational Friction**. 
Designed for seamless integration into existing banking platforms, the API ingests high-risk transactions. Behind the scenes, an AI Prosecutor and AI Defense Agent debate the transaction metadata. If deadlocked, the AI Judge issues a **subpoena** directly to the cardholder via an external channel (e.g., WhatsApp).

By adopting a strict **Model Context Protocol (MCP)** architecture, the AI agents can securely query the bank's internal transaction databases and execute communication tools without exposing raw database credentials to the LLM.

---

## 2. API-First Architecture & MCP Setup

Subpoena.ai is designed to be integrated into an institution's existing transaction pipeline via a standard RESTful interface. 

### Model Context Protocol (MCP) Implementation
To give the Gemini models secure, standardized access to the bank's data (BigQuery) and external services (Twilio), Subpoena.ai implements an **MCP Server**. 

The MCP Server exposes the following capabilities to the Gemini models:

#### A. MCP Resources (Read-Only Context)
* `user_profile://{user_id}/baselines`: Exposes the user's historical device IDs, frequent IPs, and average transfer velocities.
* `transactions://{user_id}/recent`: Provides a paginated list of the user's last 50 transactions.

#### B. MCP Tools (Executable Actions)
* `query_asn_reputation(ip_address)`: Checks an IP against known VPN/proxy lists.
* `issue_whatsapp_subpoena(user_id, context_question)`: Triggers the Twilio workflow to send a dynamic interrogation question to the user.

### System Diagram

```text
[ Client Banking Backend ] ---> (POST /v1/evaluations) ---> [ Subpoena.ai API Gateway ]
                                                                     |
                                                           [ Orchestration Engine ]
                                                                     |
+--------------------------------------------------------------------+--------------------------------+
|                                    Model Context Protocol (MCP) Server                              |
|  +--------------------+   +-----------------------+   +-----------------------+                     |
|  | Tool: Twilio Send  |   | Resource: BigQuery DB |   | Tool: Graph Search    |                     |
|  +---------+----------+   +-----------+-----------+   +-----------+-----------+                     |
+------------|--------------------------|---------------------------|---------------------------------+
             |                          |                           |
             |                          v                           |
             |           [ Gemini 1.5 Pro / Flash Agents ]          |
             |           (Prosecutor, Defense, Judge)               |
             v                                                      v
      (WhatsApp API)                                         (Neo4j/Graph DB)
```

---

## 3. Core API Endpoints

### `POST /v1/evaluations/transaction`
Initiates the multi-agent debate over a transaction. Returns a synchronous response if the agents reach a high-confidence verdict, or returns an asynchronous status if a subpoena is issued.

**Request Payload:**
```json
{
  "transaction_id": "tx_8839201",
  "user_id": "usr_9921",
  "amount": 4500.00,
  "currency": "USD",
  "metadata": {
    "ip_address": "192.168.1.44",
    "device_fingerprint": "abc-123",
    "merchant_category": "AUTO_PARTS"
  }
}
```

**Response (If Stalemate/Subpoena Issued):**
```json
{
  "evaluation_id": "eval_773",
  "status": "AWAITING_TESTIMONY",
  "debate_transcript": [
    {"agent": "Prosecutor", "argument": "Velocity spike detected..."},
    {"agent": "Defense", "argument": "Matches previous hobby purchases..."}
  ],
  "subpoena_dispatched": true
}
```

### `POST /v1/webhooks/testimony`
The webhook endpoint where external communication providers (e.g., Twilio) post the user's response. This unpauses the Judge agent's context loop.

**Request Payload:**
```json
{
  "evaluation_id": "eval_773",
  "source": "WHATSAPP",
  "message_body": "Yes, I am buying parts for my BMW E36 project."
}
```

### `GET /v1/evaluations/{evaluation_id}`
Allows the client backend or analyst dashboard to poll the final status of the investigation and retrieve the full, auditable debate transcript.

---

## 4. Multi-Agent Debate Rules & Logic

The debate is powered by distinct system prompts and rigid JSON schema enforcement.

| Agent Role | Model Configuration | Core Directive | MCP Access |
| :--- | :--- | :--- | :--- |
| **Prosecutor** | `gemini-1.5-flash` | Analyze anomalies, velocity breaches, and credential misalignment. Argue strictly for blocking. | Resources |
| **Defense** | `gemini-1.5-flash` | Correlate activity with historical edge cases and normal variance. Argue strictly for approval. | Resources |
| **Judge** | `gemini-1.5-pro` | Weigh arguments impartially. If confidence gap $< 0.25$, invoke `issue_whatsapp_subpoena` via MCP. | Resources & Tools |

### Decision Mathematical Threshold
The AI Judge calculates confidence $C$ for both Fraud ($C_f$) and Legitimate ($C_l$).
* RENDER **BLOCK** if $C_f > 0.85$
* RENDER **APPROVE** if $C_l > 0.85$
* RENDER **SUBPOENA** if $|C_f - C_l| < 0.25$ (Evidentiary Deadlock)

---

## 5. Hackathon Execution Strategy

1. **Setup MCP Environment:** Use the official `@modelcontextprotocol/sdk` to create the Node.js MCP server connecting BigQuery (mocked via local JSON/SQLite) and Twilio.
2. **Build the API Layer:** Implement the Express backend exposing the `/v1/evaluations` endpoints.
3. **Agent Orchestration:** Wire Gemini 1.5 via the Vertex AI SDK to route through the MCP server for context gathering.
4. **The "Wow" Demo:** Build a lightweight React front-end that simply *consumes* the API. Show the real-time API logs streaming the transcript on one side, and a mirrored WhatsApp screen on the other. 
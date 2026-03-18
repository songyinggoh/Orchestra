# Phase 4: Agent IAM & Security — Deep Research Report

**Researched:** 2026-03-11
**Domain:** Enterprise-grade identity and access management for multi-agent orchestration
**Confidence:** HIGH (library versions verified via PyPI/GitHub; spec statuses verified via W3C/IETF)
**Prerequisite:** Phase 3 complete (server layer, observability, basic security already in place)

---

## 1. DID (Decentralized Identifiers)

### Spec Status

| Specification | Status | Date |
|---|---|---|
| W3C DID Core 1.0 | W3C Recommendation | July 2022 |
| W3C DID Core 1.1 | Candidate Recommendation | March 2026 (exit criteria: 2+ implementations per feature) |
| did:web method | Community specification | Stable |
| did:peer method | DIF specification v2 | Stable |

DID Core 1.0 is the stable foundation. DID 1.1 is in CR and expected to reach Recommendation by mid-2026. Safe to build against 1.0 semantics now.

### DID Methods for Agent Systems

**did:web** — Web-based identifiers resolved via HTTPS. An agent's DID resolves to a DID Document hosted at a well-known URL (e.g., `did:web:orchestra.example.com:agents:summarizer-v2` resolves to `https://orchestra.example.com/agents/summarizer-v2/did.json`). Ideal for organization-controlled agents where the org already has DNS infrastructure. Depends on DNS/TLS, so not truly decentralized; implement DID Document caching with TTL.

**did:peer** — Peer-to-peer identifiers requiring no blockchain or web server. Created locally using cryptographic key material. Ideal for ephemeral agent-to-agent connections and cross-org handoffs. Not globally resolvable — both parties must exchange DID Documents out-of-band.

**did:webvh** — Evolution of did:web maintained by the Decentralized Identity Foundation. Adds a verifiable history log, enabling auditors to verify DID Document changes over time. Python implementation at `decentralized-identity/didwebvh-py`.

### Python Libraries

| Library | Version | PyPI | Purpose | Maturity |
|---|---|---|---|---|
| `peerdid` | 0.5.2 | Yes | did:peer creation & resolution (numalgo 0 and 2) | Stable, Apache 2.0, Python >=3.7 |
| `did-peer-2` | latest | Yes | did:peer:2 focused implementation | Active |
| `did-peer-4` | latest | GitHub | did:peer:4 (DIF reference implementation) | Active |
| `didkit` | 0.3.3 | Yes | DID resolution + VC issuance/verification (Rust core, PyO3 bindings) | Stable, multi-platform |
| `didwebvh-py` | latest | GitHub | did:web with version history | Active (DIF maintained) |
| `universal-resolver-python` | latest | GitHub | HTTP client for DIF Universal Resolver | Simple wrapper |
| `PyLD` | latest | Yes | JSON-LD processing (required for DID Documents) | Stable (Digital Bazaar) |

### Design Decisions

1. Use did:web for organizational agents, did:peer for ephemeral/cross-org agents. This is the standard two-method pattern.
2. `didkit` is the recommended primary library — provides both DID resolution and VC issuance/verification with Rust performance via PyO3.
3. Store DID private keys through the SecretProvider (section 7), never alongside DID Documents.
4. Non-human identity scale is massive: NHIs outnumber human identities 90:1 to 100:1 in enterprise environments (Identiverse 2025), up to 40,000:1 in cloud-native environments. Agent frameworks must design for this scale.

### Pitfalls
- did:web depends on DNS/TLS — if the hosting server is down, identity verification fails. Cache DID Documents.
- did:peer DIDs are not globally resolvable. Both parties must exchange DID Documents during handoff initialization.
- DIDKit Python wheels are platform-specific (built from Rust). CI/CD must handle Linux/macOS/Windows.

---

## 1.1 Gossip Poisoning — Signed Agent Cards

### Rationale: The "Dark Room" Risk
In a decentralized A2A (Agent-to-Agent) network using gossip for discovery, the network is a "dark room" where any node can broadcast a fake Agent Card, impersonating a high-privilege agent or a trusted router. Without identity verification, the gossip protocol is vulnerable to poisoning.

### Implementation: Cryptographic Signatures
Mandate **Cryptographic Signatures** for all Agent Cards broadcast over the network.

- **Verification:** Every Agent Card must be signed by the agent's private key (linked to its DID).
- **Root of Trust:** Verification against the `did:web` or `did:peer` root must be a prerequisite for any agent-to-agent tool call or handoff.
- **P1 Action:** Implement a `SignedDiscoveryProvider` that discards any Agent Card with an invalid signature or an unresolvable DID.

---

## 2. AgentIdentity

### Core Design

AgentIdentity is the identity attribute carried in `AgentContext`. It must be cryptographically verifiable (backed by a DID), propagatable through distributed agent calls, and carry authorization claims (via VCs).

### Recommended Data Model

```python
@dataclass(frozen=True)
class AgentIdentity:
    did: str                           # e.g., "did:web:example.com:agents:summarizer"
    controller_did: str                # DID of the controlling entity
    display_name: str
    roles: tuple[str, ...]             # e.g., ("summarizer", "reader")
    capabilities: tuple[str, ...]      # e.g., ("tool:web_search", "tool:file_read")
    max_delegation_depth: int = 1      # Bounded delegation chain
    issuer_did: str = ""
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    verified_credentials: tuple = ()
```

Key properties: immutable (frozen dataclass), delegation creates a new identity with reduced depth and subset capabilities, controller_did creates an auditable accountability chain.

### Identity Propagation

**In-process / across services:** Use OpenTelemetry Baggage (W3C Baggage headers) to propagate agent DID, controller DID, and delegation depth through HTTP calls. Orchestra already uses OTel, so this builds on existing infrastructure.

**Cross-organization:** Use DIDComm v2 messages carrying signed identity assertions. The receiving agent verifies the DID signature before accepting the delegated identity.

### Integration with Existing Orchestra

Add `identity: Optional[AgentIdentity]` to `AgentContext`. When identity is `None`, the agent operates in legacy mode (no IAM enforcement), enabling incremental adoption.

---

## 3. Verifiable Credentials (VC)

### Spec Status

The entire VC 2.0 family reached W3C Recommendation status in May 2025: VC Data Model 2.0, VC Data Integrity 1.0, EdDSA Cryptosuites 1.0, ECDSA Cryptosuites 1.0, Securing VCs using JOSE and COSE, Controlled Identifiers 1.0, and Bitstring Status List 1.0. This is a stable foundation.

### How Agents Use VCs

1. **Capability Credentials** — Organization issues a VC to an agent asserting its capabilities; agent presents this VC when requesting tool access.
2. **Delegation Credentials** — Orchestrator issues a VC to a sub-agent asserting delegated permissions.
3. **Cross-Org Trust** — Agents from different organizations exchange VCs to establish trust without a shared IdP.

### Python Libraries

| Library | Version | Purpose | Status |
|---|---|---|---|
| `didkit` | 0.3.3 | VC issuance + verification (primary recommendation) | Stable, Rust core |
| `PyLD` | latest | JSON-LD processing for VC documents | Stable |
| `aries-cloudagent` (ACA-Py) | 1.4.0 | Full-stack agent with VC support | Active (OpenWallet Foundation) |

ACA-Py 1.4.0 introduced "Kanon Storage" (modular storage separating key management from data persistence) and supports both AnonCreds and W3C VC formats with BBS+ Signatures. However, ACA-Py is a full agent framework, not a library — use `didkit` for VC operations and reference ACA-Py patterns.

### Design Decisions

1. Issue short-lived VCs (1-24 hour validity) for agent sessions, not long-lived certificates.
2. Use VC Data Model 2.0 (`validFrom`/`validUntil`), not 1.1.
3. Start with JOSE/COSE securing (JWT-based VCs) for simplicity. JSON-LD Data Integrity provides better selective disclosure but requires more infrastructure.
4. Cache JSON-LD contexts locally — context resolution requires network access.

---

## 4. OIDC Bridge

### Purpose

Connect enterprise IdPs (Okta, Auth0, Azure AD/Entra ID) to Orchestra's agent identity system. Employee authenticates via SSO; OIDC tokens map to AgentIdentity with capability assignments.

### Python Libraries

| Library | Version | Purpose | Recommendation |
|---|---|---|---|
| `Authlib` | 1.6.9 | OAuth2/OIDC client + server, JWT | **Primary** |
| `joserfc` | latest | JOSE RFC implementation (JWT/JWS/JWE/JWK) | Used by Authlib 1.7+; standalone option |
| `python-jose` | 3.5.0 | JWT encoding/decoding (2.7M weekly downloads) | Widely used but `joserfc` is the modern replacement |
| `idpyoidc` | latest | Full OIDC Provider + RP implementation | Feature-rich but heavy |
| `fastapi-authlib-oidc` | latest | FastAPI + Authlib integration | Good fit since Orchestra uses FastAPI |

### Authlib 1.6.x Details (Released May 2025)

- OIDC UserInfo endpoint support
- Dynamic Client Registration
- ACR and AMR claims in id_token
- Auto token refresh 60 seconds before expiry
- Three OAuth2 client implementations: `requests_client`, `httpx_client`, framework integrations

**joserfc vs python-jose:** `joserfc` provides built-in type hints, supports both JWS and JWE modes, and supports both compact and JSON serialization. For new projects, prefer `joserfc`.

### Architecture

The OIDC Bridge validates id_tokens, extracts claims (sub, roles), maps OIDC roles to Orchestra capabilities via configurable mapping, creates/resolves an agent DID derived from the OIDC subject (`did:web:{issuer}:users:{sub}`), and returns an AgentIdentity.

### Pitfalls
- Cache JWKS with 5-15 minute TTL.
- Different IdPs use different claim names for roles (`roles`, `groups`, `realm_access.roles` for Keycloak). Handle provider-specific extraction.
- Token lifetimes vary: Auth0 defaults to 24h, Okta to 1h. Agent sessions must handle expiry.

---

## 5. Capability-Based Security (zcap-ld / UCAN)

### Recommendation: Use UCAN over ZCAP-LD

| Feature | ZCAP-LD | UCAN |
|---|---|---|
| Spec status | W3C CCG Draft v0.3 (stagnant) | Independent spec (ucan.xyz), active |
| Format | JSON-LD with Linked Data Proofs | JWT-based with DID principals |
| Python library | **None** | `py-ucan` 1.0.0 on PyPI |
| Delegation | Capability chain with caveats | Token chain with proofs array |

UCAN provides trustless, secure, local-first authorization with public-key verifiability, delegability, and expressive capabilities. Principals are represented by DIDs, making it a natural fit for the DID-based identity system.

### py-ucan Library

- **Version:** 1.0.0 on PyPI
- **Foundation:** Pydantic v2 models
- **Components:** `ResourcePointer` (e.g., `orchestra://tools/web_search`), `Ability` (e.g., `tool/invoke`), `Capability`

### Integration with Existing ACLs

Implement UCAN as an authorization layer above the existing ACL system. ACLs become the "root" authority; UCANs are delegation tokens derived from ACL-granted capabilities. This enables attenuated delegation (sub-agent gets tool access with a 10-call limit), offline verification, and transitive delegation with bounded depth.

---

## 5.1 ZCAP-LD Revocation — Short-Lived Capabilities (TTLs)

### Rationale: The "Ghost Capability" Risk
The primary risk with capability-based security (ZCAP-LD/UCAN) is the "ghost capability" — a delegated token that persists after the delegator's intent has changed. While real-time Revocation Lists (CRL) are the ultimate solution, they are complex to manage at agent-scale and introduce a single point of failure (the revocation authority).

### Implementation: Short-Lived Tokens (TTLs)
Use **Short-Lived Capabilities (TTLs)** as the primary defense mechanism.

- **Policy:** Capabilities must have a TTL of 1–60 minutes depending on task sensitivity.
- **Workflow:** Sub-agents must request refreshed capabilities from their parent for long-running workflows.
- **P2 Action:** Use Short-Lived Capabilities as the primary defense, moving toward a real-time Revocation List (Status List 2021) later in the phase.

---

## 6. Zero-Knowledge Proofs (ZKP)

### Use Case

Cross-org agent handoffs where an agent needs to prove it has a capability without revealing its full identity or all permissions.

### Practical ZKP Schemes

| Scheme | Python Support | Recommendation |
|---|---|---|
| **BBS+ Signatures** | `ursa-bbs-signatures` (deprecated/archived), `py-ecc` 8.0.0 (low-level) | Primary for VCs, but no production-ready Python lib |
| **zk-SNARKs** | `py-ecc` 8.0.0 (BLS12-381 curves), circom (JS/WASM only) | Defer — no Python ecosystem |
| **Schnorr Proofs** | `zksk` library (academic, petlib/OpenSSL bindings) | Good for simple cases |

### Current State

There is no production-ready, actively maintained Python BBS+ library. Hyperledger Ursa (which had Python BBS+ bindings) is archived. MATTR rebuilt BBS in Rust with wrappers for Java/Obj-C/C/WASM but no Python wrapper. The IETF BBS draft is still progressing.

`py-ecc` 8.0.0 (Ethereum Foundation) provides BLS12-381 pairing operations needed for BBS+, but the BBS+ protocol would need to be built on top. The library is experimental and NOT audited.

### Recommended Approach

1. **Initial:** Use selective disclosure via multiple VCs (issue separate VCs per capability, present only relevant ones). No ZKP complexity needed.
2. **Later:** Implement BBS+ via MATTR's Rust library with Python FFI when a wrapper becomes available.
3. **Skip zk-SNARKs entirely.** The circom/snarkjs ecosystem is JavaScript/WASM-centric with no mature Python integration.

---

## 6.1 ZKP State Injection — Input Hash Commitments

### Rationale: Cross-Organization State Forgery
A "Tier 3" attacker with deep knowledge of the ZKP circuit could forge a proof that an agent has a specific state (e.g., "this user is a VIP") during a cross-organization handoff. Without tying the proof to the original data, a ZKP can become a vehicle for injecting malicious or fake state.

### Implementation: Commitment Circuits
Implement **Input Hash Commitments** within the ZKP circuit to ensure proofs are tied to verified historical data.

- **Hash Commitment:** The ZKP must include a commitment (hash) of the input data as a public signal.
- **Verification:** The recipient agent must verify that the commitment matches the hash of the shared (but selectively disclosed) data.
- **P2 Action:** Implement Input Hash Commitments in the ZKP circuit to ensure proofs are tied to verified, non-forged historical state.

---

## 7. SecretProvider

### Backend Libraries

| Backend | Library | Version | Python Support |
|---|---|---|---|
| HashiCorp Vault | `hvac` | 2.4.0 (Oct 2025) | 3.8-3.12 |
| AWS Secrets Manager | `boto3` (secretsmanager) | latest | 3.8+ |
| GCP Secret Manager | `google-cloud-secret-manager` | latest (Dec 2025) | 3.7+ |
| Azure Key Vault | `azure-keyvault-secrets` | latest | 3.8+ |
| OpenBao (Vault fork, MPL 2.0) | `hvac` (compatible) | 2.4.0 | 3.8-3.12 |
| Local/Dev | `python-dotenv` | latest | 3.8+ |

Additional: `secretsmith` (Sept 2025) provides a simplified Python helper for Vault/OpenBao with AppRole auth and metadata support.

### hvac Details

`hvac` 2.4.0 supports Vault v1.4.7+, KV secrets (v1/v2), Transit encryption, PKI, and multiple auth methods (AppRole, Kubernetes, LDAP, Token). Also compatible with OpenBao, the Linux Foundation-hosted open-source fork of Vault under MPL 2.0.

### Recommended Architecture

Abstract provider pattern (`SecretProvider` ABC) with implementations for Vault, AWS, GCP, Azure, and local environment. Key design points:
- Vault preferred for production (dynamic credentials eliminate rotation)
- Pre-fetch and cache secrets with TTL shorter than secret expiry
- DID signing keys must go through SecretProvider
- `hvac` is synchronous; wrap in `asyncio.to_thread()` for async Orchestra

---

## 8. SOC2 Readiness

### Relevant Trust Services Criteria

| Criteria | Area | Agent Framework Requirements |
|---|---|---|
| **CC6** | Logical & Physical Access | Agent RBAC/UCAN, tool ACLs, least-privilege, short-lived credentials |
| **CC7** | System Operations & Monitoring | Centralized logging, immutable audit trails (1+ year retention), anomaly detection, real-time alerting |
| **CC8** | Change Management | Agent version tracking, graph versioning, deployment audit trail |

### Encryption Requirements
- AES-256 for data at rest (stored secrets, agent state, memory tiers)
- TLS 1.2+ for all communication
- Key rotation every 90 days; HSM or cloud KMS for storage

### Agent-Specific SOC2 Requirements (2025 Guidance)
- Complete, immutable logs of every agent decision required for regulatory review (CC7.2/CC7.3)
- Every log entry must be attributable to a specific agent identity (DID) and its controller
- AI agent access controls must use least-privilege with time-bound elevated rights (CC6)
- Continuous monitoring with centralized, immutable logging for at least 1 year

### Compliance Status vs. Orchestra

| Control | Current Status | Phase 4 Work Needed |
|---|---|---|
| Access control (CC6.1) | Exists (Phase 2 ACLs) | Extend with UCAN, RBAC |
| Least privilege (CC6.3) | Partial | Capability-scoped identities |
| Encryption at rest | TODO | Encrypt SQLite state, memory |
| Encryption in transit | Exists (TLS on FastAPI) | — |
| Audit logging (CC7.2) | Partial (OTel traces) | Dedicated immutable audit log |
| Monitoring (CC7.3) | Partial (OTel metrics) | Alerting rules |
| Change management (CC8.1) | TODO | Graph/agent version tracking |
| Key management | TODO | SecretProvider + rotation |

Plan for SOC 2 Type I readiness in Phase 4 (point-in-time control verification), with Type II evidence collection (6+ months of operational evidence) ongoing.

---

## Implementation Priority

**Wave 1 (Weeks 1-3): Foundation**
- T-4.1: SecretProvider (`hvac` 2.4.0, `boto3`, `google-cloud-secret-manager`) — unblocks all IAM
- T-4.2: AgentIdentity + DID (`peerdid` 0.5.2, `didkit` 0.3.3) — core identity model

**Wave 2 (Weeks 4-6): Authorization**
- T-4.3: Verifiable Credentials (`didkit` 0.3.3)
- T-4.4: OIDC Bridge (`Authlib` 1.6.9, `joserfc`)
- T-4.5: UCAN Delegation (`py-ucan` 1.0.0)

**Wave 3 (Weeks 7-9): Compliance**
- T-4.6: SOC2 Audit Logging (immutable events, integrity hashing)
- T-4.7: SOC2 Documentation (policies, control mapping)

**Wave 4 (Weeks 10+, if needed):**
- T-4.8: ZKP/BBS+ Selective Disclosure (`py-ecc` 8.0.0)

**Skip:** zk-SNARKs/circom (no Python ecosystem), full ACA-Py integration (overkill), DID blockchain anchoring (unnecessary complexity), ZCAP-LD (no Python library, use UCAN instead).

### pyproject.toml Dependencies

```toml
[project.optional-dependencies]
iam = [
    "didkit>=0.3.3", "peerdid>=0.5.2", "PyLD>=2.0",
    "Authlib>=1.6.9", "joserfc>=1.0",
    "py-ucan>=1.0.0", "hvac>=2.4.0",
]
iam-aws = ["boto3"]
iam-gcp = ["google-cloud-secret-manager"]
iam-azure = ["azure-keyvault-secrets"]
iam-zkp = ["py-ecc>=8.0.0"]
```

┌────────────────────────────┐
│       Client Request       │
│   (includes AST payload)   │
└───────────────┬────────────┘
                │
                ▼
┌────────────────────────────┐
│  1. Assemble QuerySet      │
│  - Use the ORM provider    │
│  - Consider:               │
│     • Request object       │
│     • Initial AST query    │
│     • Custom QuerySet(s)   │
│     • Model default query  │
│     • Registered permissions │
└───────────────┬────────────┘
                │
                ▼
┌────────────────────────────┐
│  2. Process the Query      │
│  - Apply AST instructions  │
│    (filters, sorting, etc.)│
│  - Also supports create    │
│    operations via AST       │
└───────────────┬────────────┘
                │
                ▼
┌────────────────────────────┐
│  3. Serialize the Data     │
│  - Custom serializers      │
│  - Pre/Post hooks, depth,  │
│    and field selection     │
└───────────────┬────────────┘
                │
                ▼
┌────────────────────────────┐
│  4. Generate the Schema    │
│  - Model introspection and │
│    custom overrides        │
└───────────────┬────────────┘
                │
                ▼
┌────────────────────────────┐
│  5. Emit the Event         │
│  - Use a pluggable event   │
│    emitter (WebSockets,    │
│    message queues, etc.)   │
└───────────────┬────────────┘
                │
                ▼
┌────────────────────────────┐
│     Client Response        │
└────────────────────────────┘
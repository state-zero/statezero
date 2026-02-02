# StateZero

**The Real-Time Django to JavaScript Data Bridge**

Connect your Django backend to React/Vue frontends with 90% less code. No repetitive serializers, views, or tight coupling.

## Why StateZero?

**The Problem:** Building modern web apps means writing the same CRUD logic three times - Django models, REST API serializers/views, and frontend data fetching. This creates:

- 80% of app complexity in data shuttling
- 50% of your codebase devoted to API glue
- Hundreds of hours maintaining sync between frontend and backend

**The Solution:** StateZero eliminates the API layer entirely. Write Django models once, query them directly from JavaScript with the same ORM syntax you already know.

## Features

✨ **Django ORM Syntax in JavaScript** - Use `.filter()`, `.exclude()`, `.orderBy()` exactly like Django  
⚡ **Real-Time Updates** - UI automatically updates when backend data changes  
🔒 **Django Permissions** - Your existing permission classes work on the frontend  
📝 **Auto-Generated TypeScript** - Perfect type safety from your Django models  
🚀 **Optimistic Updates** - UI feels instant, syncs in background  
🔗 **Deep Relationships** - Traverse foreign keys naturally: `todo.category.name`

## Quick Example

### 1. Register Your Django Model

```python
# todos/crud.py
from statezero.adaptors.django.config import registry
from .models import Todo

registry.register(Todo)
```

### 2. Query From JavaScript Like Django

```javascript
// Get all incomplete todos, ordered by priority
const todos = Todo.objects
  .filter({ is_completed: false })
  .orderBy("-priority", "created_at");

// Complex queries with relationships
const urgentWorkTodos = Todo.objects.filter({
  priority: "high",
  category__name: "Work",
  due_date__lt: "2024-12-31",
});

// Django-style field lookups
const searchResults = Todo.objects.filter({
  title__icontains: "meeting",
  created_by__email__endswith: "@company.com",
});
```

### 3. Real-Time Updates in One Line

```vue
<script setup>
import { useQueryset } from "@statezero/core/vue";

// This list automatically updates when todos change
const todos = useQueryset(() => Todo.objects.filter({ is_completed: false }));
</script>

<template>
  <div v-for="todo in todos.fetch({ limit: 10 })" :key="todo.id">
    {{ todo.title }}
  </div>
</template>
```

## The Magic: Optimistic vs Confirmed

### Optimistic (Instant UI)

```javascript
// UI updates immediately, syncs later
const newTodo = Todo.objects.create({
  title: "Buy groceries",
  priority: "medium",
});

// Edit optimistically
todo.title = "Buy organic groceries";
todo.save(); // UI updates instantly

// Delete optimistically
todo.delete(); // Gone from UI immediately
```

### Confirmed (Wait for Server)

```javascript
// Wait for server confirmation
const confirmedTodo = await Todo.objects.create({
  title: "Important meeting",
});

// Wait for update confirmation
await todo.save();

// Wait for deletion confirmation
await todo.delete();
```

## Advanced Django ORM Features

### Complex Filtering with Q Objects

```javascript
import { Q } from "@statezero/core";

// Multiple OR conditions
const urgentTodos = Todo.objects.filter({
  Q: [Q("OR", { priority: "high" }, { due_date__lt: "tomorrow" })],
});

// Nested conditions
const myImportantTodos = Todo.objects.filter({
  Q: [
    Q(
      "AND",
      { assigned_to: currentUser.id },
      Q("OR", { priority: "high" }, { is_flagged: true })
    ),
  ],
});
```

### Aggregation & F Expressions

```javascript
import { F } from "@statezero/core";

// Count, sum, average like Django
const todoCount = await Todo.objects.count();
const avgPriority = await Todo.objects.avg("priority_score");

// Database-level calculations
await Product.objects.update({
  view_count: F("view_count + 1"),
  popularity: F("likes * 2 + shares"),
});
```

### Get or Create

```javascript
// Just like Django's get_or_create
const [todo, created] = await Todo.objects.getOrCreate(
  { title: "Daily standup" },
  { defaults: { priority: "medium", category: workCategory } }
);
```

### Relationship Traversal

```javascript
// Access related objects naturally
const todo = await Todo.objects.get({ id: 1 });
console.log(todo.category.name); // Foreign key
console.log(todo.created_by.username); // Another FK
console.log(todo.comments.length); // Reverse FK

// Filter by relationships
const workTodos = Todo.objects.filter({
  category__name: "Work",
  assigned_to__department__name: "Engineering",
});
```

## Installation

### Backend

```bash
pip install statezero
pip install django-cors-headers pusher
```

### Frontend

```bash
npm i @statezero/core
```

### Generate TypeScript Models

```bash
npx statezero sync
```

## Why Choose StateZero Over...

**🆚 HTMX:** Use modern React/Vue with full JavaScript ecosystem while keeping backend simplicity

**🆚 Firebase/Supabase:** Keep your Django backend, models, and business logic. No vendor lock-in.

**🆚 OpenAPI/GraphQL:** Get real-time updates and Django ORM power, not just basic CRUD

**🆚 Traditional REST APIs:** Write 90% less boilerplate. Focus on features, not data plumbing.

## Testing (Backend-Mode)

StateZero supports frontend tests that run against a real Django test server (no test-only views).
You opt-in via a test-only middleware that temporarily relaxes permissions and silences events
when a request includes special headers.

### Backend Setup (Django Test Settings)

Add the test middleware and enable test mode in your **test settings**:

```python
# tests/settings.py
STATEZERO_TEST_MODE = True
STATEZERO_TEST_SEEDING_SILENT = True  # default behavior, silences events during seeding

MIDDLEWARE = [
    # ...
    "statezero.adaptors.django.testing.TestSeedingMiddleware",
    # ...
]
```

Behavior:
- `X-TEST-SEEDING: 1` → temporarily allows all permissions for the request
- `X-TEST-RESET: 1` → deletes all registered StateZero models for the request

Auth note:
- Test mode does **not** bypass authentication. Your test server must still
  authenticate requests (e.g., create a test token).

Start the test server:

```bash
python manage.py statezero_testserver --addrport 8000
```

Optional request hook:

```python
# tests/settings.py
STATEZERO_TEST_REQUEST_CONTEXT = "myapp.test_utils.statezero_test_context"
```

Your factory should accept the request and return a context manager. This allows
libraries like django-ai-first to wrap each test request (e.g., time control).

Optional startup hook (for creating test users/tokens):

```python
# tests/settings.py
STATEZERO_TEST_STARTUP_HOOK = "myapp.test_utils.statezero_test_startup"
```

```python
# myapp/test_utils.py
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

def statezero_test_startup():
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(
        username="test_user", defaults={"email": "test@example.com"}
    )
    user.set_password("test123")
    user.is_staff = True
    user.is_superuser = True
    user.save()

    token, _ = Token.objects.get_or_create(
        user=user, defaults={"key": "testtoken123"}
    )
    if token.key != "testtoken123":
        token.key = "testtoken123"
        token.save()
```

### Frontend Setup (Vue / JS)

Use the testing helpers and the `remote` manager to call the backend directly without local updates.

```javascript
import {
  setupTestStateZero,
  seedRemote,
  resetRemote,
  createActionMocker,
} from "@statezero/core/testing";
import { getModelClass } from "../model-registry";
import { ACTION_REGISTRY } from "../action-registry";
import { Todo } from "../models/default/django_app/todo";
import { vueAdapters } from "./statezero-adapters";

const testHeaders = setupTestStateZero({
  apiUrl: "http://localhost:8000/statezero",
  getModelClass,
  adapters: vueAdapters,
});

// Reset: deletes all registered StateZero models on the backend
await resetRemote(testHeaders, () => Todo.remote.delete());

// Seed: run standard ORM writes with X-TEST-SEEDING enabled
await seedRemote(testHeaders, () =>
  Todo.remote.create({ title: "Seeded todo" })
);

// Action mocking for frontend tests
const actionMocker = createActionMocker(ACTION_REGISTRY);
actionMocker.mock("send_notification", async () => ({ ok: true }));
```

Notes:
- `Model.remote` (or `Model.objects.remote()`) uses the normal ORM AST/serializers,
  but **skips local store updates** and **returns raw backend responses**.
- These helpers are intended for tests that run against a live Django test server.

## Get Started

Check out the docs at [Statezero Docs](https://statezero.dev)

Run `pip install statezero` and `npm i @statezero/core` to begin.

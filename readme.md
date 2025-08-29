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

## Get Started

Check out the docs at [Statezero Docs](https://statezero.dev)

Run `pip install statezero` and `npm i @statezero/core` to begin.
# ModelSync (Preview Release)

> Eliminate full-stack boilerplate by automatically generating type-safe frontend models from your backend.

**⚠️ Note:** This is an early preview release intended for testing and feedback. The code should not be considered ready for production use at this time. We welcome your input to help shape the future of ModelSync!

ModelSync connects your backend models directly to your frontend with zero boilerplate, enabling intuitive, type-safe data access that works with modern frontend frameworks like React, Vue, and Svelte.

## Key Features

- 🚀 **90% Less Code**: No more repetitive API layers, serializers, or TypeScript interfaces
- 🔒 **Type Safety**: End-to-end type safety from backend to frontend
- ⚡ **Real-Time Ready**: Built-in support for live data synchronization
- 🌐 **Framework Agnostic**: Works with React, Vue, Svelte and vanilla JavaScript
- 🛡️ **Permissions Built-In**: Granular access control that works across the stack

## How It Works

### 1. Define your models (Django)

```python
# models.py
from django.db import models

class Post(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
```

### 2. Register with ModelSync

```python
# crud.py
from modelsync.adaptors.django.config import registry
from modelsync.adaptors.django.permissions import IsAuthenticatedPermission
from .models import Post

registry.register(
    model=Post,
    filterable_fields={'title', 'content', 'author', 'published', 'created_at'},
    permissions=[IsAuthenticatedPermission]
)
```

### 3. Generate TypeScript Models

```bash
# In your frontend project
npx modelsync sync-models
```

### 4. Use in your frontend

```typescript
// React example
import { Post } from './models';
import { useEffect, useState } from 'react';

function PostList() {
  const [posts, setPosts] = useState([]);
  
  useEffect(() => {
    // Fetches posts with Django-like query syntax
    async function loadPosts() {
      const data = await Post.objects
        .filter({ published: true })
        .orderBy('-created_at')
        .fetch();
      setPosts(data);
    }
    
    loadPosts();
  }, []);
  
  return (
    <div>
      <h1>Posts</h1>
      {posts.map(post => (
        <div key={post.id}>{post.title}</div>
      ))}
    </div>
  );
}
```

## Real-time Data (Optional)

```typescript
import { liveView } from '@modelsync/core';

// Create a live connection to your data
const postsLive = await liveView(
  Post.objects.filter({ published: true })
);

// Data updates automatically when changes happen on the server
const posts = await postsLive.fetch();

// Create, update, and delete operations are automatically synced
await postsLive.create({ 
  title: 'New Post', 
  content: 'Content'
});
```

## Documentation

For detailed documentation on setup, configuration, and usage:

- [Getting Started](https://docs.modelsync.dev/getting-started)
- [Backend Setup (Django)](https://docs.modelsync.dev/getting-started/backend-setup-django)
- [Frontend Integration](https://docs.modelsync.dev/getting-started/frontend-config-common)
- [Permissions](https://docs.modelsync.dev/advanced/permissions)
- [Query Syntax](https://docs.modelsync.dev/advanced/query-syntax)

## Current Status & Roadmap

ModelSync currently supports Django for the backend, with support for FastAPI, Flask, and SQLAlchemy in active development. For the frontend, it works with React, Vue, and Svelte.

### Coming Soon

- **SQLAlchemy Support**: Expanded ORM compatibility for Python frameworks
- **FastAPI & Flask Integration**: First-class support for modern Python API frameworks
- **Auto-Generated UI Components**: CRUD data tables and forms that automatically sync with your models

## License

ModelSync is provided under a **Placeholder License for 6-Month Trial**:

- Free 6-month trial for all users
- Free for organizations with annual revenue under $2.5 million
- Commercial license required for organizations with annual revenue over $2.5 million after trial period
- Contact robert.herring@resipilot.com for licensing questions

See full license terms for details.
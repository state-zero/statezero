# ORMBridge

**The Real-Time Django to JavaScript Data Bridge**

Connect your Django backend to React/Vue frontends with 90% less code.  
No repetitive serializers, views or tight coupling.

[Get Started](https://www.ormbridge.com/walkthrough/) | 
[Documentation](https://ormbridge.com)

## The Python-JavaScript Disconnect

**Python** is great for backends. **JavaScript** is great for frontends. **Connecting them is a nightmare.**

Developers know this painful truth:
* **80%** of app complexity
* **50%** of your total codebase
* **Hundreds of hours** of your time

**...on code code that shuttles data between your database and your users.**

**ORMBridge eliminates this entirely.**

## Features at a Glance

- **Django-like Query Syntax** in JavaScript
- **Real-Time Updates** with one line of code
- **Automatic TypeScript Generation** from Django models
- **Granular Security Controls** using Django permissions
- **Deep Relationship Traversal** for complex data needs

## How It Works

### Backend: Connect your Django models

```python
# Register your existing Django models with ORMBridge
from ormbridge.adaptors.django.config import registry

registry.register(model=Post)
```

### Frontend: Query your backend with familiar syntax

```typescript
// Query your backend data with Django-like syntax
const posts = await Post.objects
  .filter({ is_published: true })
  .orderBy('-created_at')
  .fetch();
```

### Real-Time in One Line

```typescript
// Vue component with real-time updates
const posts = ref([]);
createVueLiveView(Post.objects.filter({ is_published: true }), posts);

// React component with real-time updates
const [posts, query, loading] = useReactLiveView(
  Post.objects.filter({ is_published: true })
);
```

## Quick Setup

### 1. Install Backend Dependencies

```bash
pip install django djangorestframework
pip install git+https://github.com/ormbridge/ormbridge
pip install django-cors-headers pusher
```

### 2. Install Frontend Package

```bash
# In your React/Vue project
npm install https://github.com/ormbridge/ormbridge-client
```

### 3. Generate TypeScript Models

Run your backend in development mode with:

```bash
python manage.py runserver
```

And run:

```bash
npx ormbridge sync-models
```

## Why Choose ORMBridge?

### Over HTMX
- **Modern JS Frontend:** Use modern JS frameworks (React, Vue) and UI libraries (Shadcn, Tailwind)
- **Avoid Coupling:** Your frontend and backend codebases remain decoupled

### Over Backend-for-Frontend (e.g., Supabase, Firebase)
- **Keep Your Backend:** No need to adopt a new backend service
- **Permissions As Code:** Django permissions directly on frontend

### Over OpenAPI Schema and Client Generators
- **Real-Time In One Line:** Your UI will automatically re-render when your backend data changes
- **Advanced Querying:** Rich Django-style ORM queries, not just basic CRUD
- **Integrated Permissions:** Directly leverage Django's permissions

## Advanced Query Example

```typescript
// Complex queries that map directly to Django's ORM functionality
const featuredTechPosts = await Post.objects.filter({
  is_published: true,
  author__department: 'Engineering',
  Q: [
    Q('OR', 
      { is_featured: true }, 
      { view_count__gt: 1000 }
    )
  ]
}).fetch();
```

## Full Documentation

For complete setup instructions, advanced usage, and API references, visit:

📖 [ormbridge.com](https://ormbridge.com)

## License

ORMBridge is available under a free commercial license. You can use it in both personal and commercial projects at no cost.
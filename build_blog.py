import os
import re
import markdown
from jinja2 import Environment, FileSystemLoader

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BLOG_DIR = os.path.join(BASE_DIR, 'blog')
POSTS_DIR = os.path.join(BLOG_DIR, 'posts')
TEMPLATES_DIR = os.path.join(BLOG_DIR, 'templates')
OUTPUT_DIR = BLOG_DIR

def parse_frontmatter(content):
    """
    Simple frontmatter parser.
    Supports title, date, author, description.
    """
    frontmatter = {}
    body = content
    match = re.search(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
    if match:
        yaml_content = match.group(1)
        body = match.group(2)
        for line in yaml_content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' in line:
                key, value = line.split(':', 1)
                frontmatter[key.strip()] = value.strip()
    return frontmatter, body

def build_blog():
    # Setup Jinja2 environment
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    post_template = env.get_template('post.html')
    index_template = env.get_template('index.html')

    posts_metadata = []

    # Process each markdown file
    if not os.path.exists(POSTS_DIR):
        print(f"Posts directory not found: {POSTS_DIR}")
        return

    for filename in os.listdir(POSTS_DIR):
        if filename.endswith('.md'):
            filepath = os.path.join(POSTS_DIR, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            metadata, body = parse_frontmatter(content)
            
            # Convert Markdown to HTML
            html_content = markdown.markdown(body)
            
            # Prepare context for template
            context = metadata.copy()
            context['content'] = html_content
            
            # Output filename
            post_filename = filename.replace('.md', '.html')
            output_path = os.path.join(OUTPUT_DIR, post_filename)
            
            # Render and write
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(post_template.render(context))
            
            print(f"Generated: {post_filename}")

            # Add to list for index
            summary = metadata.copy()
            summary['url'] = post_filename
            posts_metadata.append(summary)

    # Sort posts by date (require 'date' in frontmatter)
    posts_metadata.sort(key=lambda x: x.get('date', ''), reverse=True)

    # Render Index
    index_output_path = os.path.join(OUTPUT_DIR, 'index.html')
    with open(index_output_path, 'w', encoding='utf-8') as f:
         f.write(index_template.render(posts=posts_metadata))
    
    print("Blog index generated.")

    # Update Homepage (index.html)
    update_homepage(posts_metadata)

def update_homepage(posts):
    homepage_path = os.path.join(BASE_DIR, 'index.html')
    if not os.path.exists(homepage_path):
        print("Homepage index.html not found.")
        return

    # Generate HTML for latest posts (max 3)
    latest_posts = posts[:3]
    posts_html = ""
    for post in latest_posts:
        # Link from root needs 'blog/' prefix
        url = f"blog/{post['url']}"
        date = post.get('date', '')
        title = post.get('title', 'Untitled')
        desc = post.get('description', '')
        
        posts_html += f"""
        <div class="post-preview" style="margin-bottom: 1.5rem; border-bottom: 1px solid #eee; padding-bottom: 1rem;">
            <h3 style="margin-bottom: 0.5rem;"><a href="{url}" style="text-decoration: none; color: inherit;">{title}</a></h3>
            <div style="font-size: 0.9rem; color: #666; margin-bottom: 0.5rem;">{date}</div>
            <p style="margin-bottom: 0; color: #444;">{desc}</p>
        </div>
        """
    
    with open(homepage_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Regex to find the block
    pattern = re.compile(r'(<!-- BLOG_POSTS_START -->)(.*?)(<!-- BLOG_POSTS_END -->)', re.DOTALL)
    
    if pattern.search(content):
        updated_content = pattern.sub(fr'\1\n{posts_html}\n\3', content)
        with open(homepage_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        print("Homepage updated with latest posts.")
    else:
        print("Could not find blog posts placeholder in index.html")

if __name__ == "__main__":
    build_blog()

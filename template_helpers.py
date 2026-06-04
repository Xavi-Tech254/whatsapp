from markupsafe import Markup
from models import Category

def render_node(cat, depth):
    indent = depth * 14
    type_badge = ''
    header_class = 'node-header'
    if cat.cat_type == 'file':
        type_badge = '<span class="badge-type pill-y">📎 File</span>'
        header_class = 'node-header has-file'
    elif cat.cat_type == 'link':
        type_badge = '<span class="badge-type pill-b">🔗 Link</span>'
        header_class = 'node-header has-link'
    else:
        type_badge = '<span class="badge-type pill-g">📁 Folder</span>'
        header_class = 'node-header is-folder'

    price_html = ''
    if cat.price > 0:
        price_html = f'<span class="node-price">Ksh {int(cat.price)}</span>'
    elif cat.cat_type != 'folder':
        price_html = '<span class="node-price" style="color:var(--muted)">FREE</span>'

    inactive_class = '' if cat.is_active else ' inactive'

    # Edit button data
    link_val = cat.link or ''
    name_safe = cat.name.replace("'", "\\'")
    icon_safe = cat.icon.replace("'", "\\'")

    actions = f'''
    <div class="node-actions">
      <button class="btn btn-secondary btn-sm" onclick="openEdit({cat.id},'{name_safe}','{icon_safe}',{cat.price},'{link_val}',{'true' if cat.is_active else 'false'})">✏️</button>
      <button class="btn btn-danger btn-sm" onclick="deleteNode({cat.id})">🗑</button>
    </div>'''

    header = f'''
    <div class="{header_class}{inactive_class}">
      <span class="node-icon">{cat.icon}</span>
      <span class="node-name">{cat.name} {"🚫" if not cat.is_active else ""}</span>
      {type_badge}
      {price_html}
      {actions}
    </div>'''

    children_html = ''
    if cat.cat_type == 'folder':
        children_content = ''
        for child in sorted(cat.children, key=lambda x: x.order_index):
            children_content += render_node(child, depth + 1)

        add_form = f'''
        <div class="add-form" id="af-{cat.id}">
          <h4>➕ Add inside "{cat.name}"</h4>
          <div class="form-row">
            <div class="fg" style="flex:2"><label>Name *</label><input type="text" id="cn-{cat.id}" placeholder="Name"></div>
            <div class="fg" style="flex:0 0 70px"><label>Icon</label><input type="text" id="ci-{cat.id}" placeholder="📄" maxlength="2"></div>
          </div>
          <div style="font-size:.72rem;color:var(--muted);margin-bottom:6px">Type:</div>
          <div class="type-sel" id="ts-{cat.id}">
            <div class="type-btn active" onclick="selType({cat.id},'folder',this)">📁 Folder</div>
            <div class="type-btn" onclick="selType({cat.id},'file',this)">📎 File</div>
            <div class="type-btn" onclick="selType({cat.id},'link',this)">🔗 Link</div>
          </div>
          <div class="file-area" id="cfa-{cat.id}">
            <div class="form-row">
              <div class="fg"><label>Price (Ksh)</label><input type="number" id="cp-{cat.id}" value="0" min="0"></div>
              <div class="fg"><label>File/Link</label><input type="text" id="cl-{cat.id}" placeholder="file.pdf or https://..."></div>
            </div>
            <div class="fg" style="margin-top:6px"><label>Upload File</label><input type="file" id="cf-{cat.id}"></div>
          </div>
          <div style="display:flex;gap:8px;margin-top:10px">
            <button class="btn btn-primary btn-sm" onclick="submitSub({cat.id})">✅ Add</button>
            <button class="btn btn-ghost btn-sm" onclick="toggleForm('af-{cat.id}')">Cancel</button>
          </div>
        </div>
        <button class="btn-add-sub" onclick="toggleForm('af-{cat.id}')">➕ Add item inside "{cat.name}"</button>'''

        children_html = f'''
        <div class="node-children">
          {children_content}
          {add_form}
        </div>'''

    return f'''
    <div class="node" id="node-{cat.id}" style="margin-left:{indent}px">
      {header}
      {children_html}
    </div>'''

def register_template_helpers(app):
    @app.template_global()
    def render_node_tpl(cat, depth=0):
        return Markup(render_node(cat, depth))

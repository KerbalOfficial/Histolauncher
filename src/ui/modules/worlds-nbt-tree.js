// ui/modules/worlds-nbt-tree.js

import { unicodeList } from './config.js';

const NBT = {
  END: 0,
  BYTE: 1,
  SHORT: 2,
  INT: 3,
  LONG: 4,
  FLOAT: 5,
  DOUBLE: 6,
  BYTE_ARRAY: 7,
  STRING: 8,
  LIST: 9,
  COMPOUND: 10,
  INT_ARRAY: 11,
  LONG_ARRAY: 12,
};

const NUMERIC_TAGS = new Set([NBT.BYTE, NBT.SHORT, NBT.INT, NBT.LONG, NBT.FLOAT, NBT.DOUBLE]);
const ARRAY_TAGS = new Set([NBT.BYTE_ARRAY, NBT.INT_ARRAY, NBT.LONG_ARRAY]);

const TYPE_LABELS = {
  [NBT.END]: 'End (empty)',
  [NBT.BYTE]: 'Byte',
  [NBT.SHORT]: 'Short',
  [NBT.INT]: 'Int',
  [NBT.LONG]: 'Long',
  [NBT.FLOAT]: 'Float',
  [NBT.DOUBLE]: 'Double',
  [NBT.BYTE_ARRAY]: 'Byte Array',
  [NBT.STRING]: 'String',
  [NBT.LIST]: 'List',
  [NBT.COMPOUND]: 'Compound',
  [NBT.INT_ARRAY]: 'Int Array',
  [NBT.LONG_ARRAY]: 'Long Array',
};

const ALL_TYPE_OPTIONS = [
  NBT.BYTE,
  NBT.SHORT,
  NBT.INT,
  NBT.LONG,
  NBT.FLOAT,
  NBT.DOUBLE,
  NBT.BYTE_ARRAY,
  NBT.STRING,
  NBT.LIST,
  NBT.COMPOUND,
  NBT.INT_ARRAY,
  NBT.LONG_ARRAY,
];

const isObject = (value) => !!value && typeof value === 'object' && !Array.isArray(value);

const isFloatType = (type) => type === NBT.FLOAT || type === NBT.DOUBLE;

const isIntegerType = (type) => (
  type === NBT.BYTE
  || type === NBT.SHORT
  || type === NBT.INT
  || type === NBT.LONG
);

const defaultValueForType = (type) => {
  if (type === NBT.COMPOUND) return {};
  if (type === NBT.LIST) return { list_type: NBT.END, items: [] };
  if (ARRAY_TAGS.has(type)) return [];
  if (NUMERIC_TAGS.has(type)) return 0;
  if (type === NBT.STRING) return '';
  return null;
};

const cloneValue = (value) => {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map((item) => cloneValue(item));
  if (typeof value === 'object') {
    const next = {};
    Object.keys(value).forEach((key) => { next[key] = cloneValue(value[key]); });
    return next;
  }
  return value;
};

const wrapItemAsTag = (listType, item) => ({ type: listType, value: item });

const unwrapItemFromTag = (tag) => (isObject(tag) ? tag.value : null);

const parseIntegerInput = (raw) => {
  const text = String(raw ?? '').trim();
  if (!text) return 0;
  if (!/^-?\d+$/.test(text)) {
    throw new Error(`"${raw}" is not a valid integer.`);
  }
  return Number(text);
};

const parseFloatInput = (raw) => {
  const text = String(raw ?? '').trim();
  if (!text) return 0;
  const value = Number(text);
  if (!Number.isFinite(value)) {
    throw new Error(`"${raw}" is not a valid number.`);
  }
  return value;
};

const parseArrayInput = (raw, integerOnly) => {
  const text = String(raw ?? '').trim();
  if (!text) return [];
  return text.split(/[\s,]+/).filter(Boolean).map((token) => (
    integerOnly ? parseIntegerInput(token) : parseFloatInput(token)
  ));
};

const formatArrayValue = (items) => (Array.isArray(items) ? items.join(', ') : '');

const createTypeSelect = (currentType, { allowedTypes = ALL_TYPE_OPTIONS, includeEnd = false } = {}) => {
  const select = document.createElement('select');
  select.className = 'world-nbt-tree-type-select';

  const options = includeEnd ? [NBT.END, ...allowedTypes] : allowedTypes;
  options.forEach((type) => {
    const opt = document.createElement('option');
    opt.value = String(type);
    opt.textContent = TYPE_LABELS[type] || `Type ${type}`;
    if (type === currentType) opt.selected = true;
    select.appendChild(opt);
  });

  if (!options.includes(currentType)) {
    const opt = document.createElement('option');
    opt.value = String(currentType);
    opt.textContent = TYPE_LABELS[currentType] || `Type ${currentType}`;
    opt.selected = true;
    select.insertBefore(opt, select.firstChild);
  }

  return select;
};

// ---------------------------------------------------------------------------
// Tag node (represents a single NBT tag inside the tree)
// ---------------------------------------------------------------------------

class TagNode {
  constructor({
    name = '',
    type = NBT.END,
    value = null,
    nameEditable = true,
    onRemove = null,
    onTypeChange = null,
  } = {}) {
    this.name = String(name || '');
    this.type = Number(type) || NBT.END;
    this.value = value;
    this.nameEditable = !!nameEditable;
    this.onRemove = typeof onRemove === 'function' ? onRemove : null;
    this.onTypeChange = typeof onTypeChange === 'function' ? onTypeChange : null;
    this.collapsed = false;

    this.element = document.createElement('div');
    this.element.className = 'world-nbt-tree-node';

    this._buildHeader();
    this._buildBody();
    this._render();
  }

  _buildHeader() {
    const header = document.createElement('div');
    header.className = 'world-nbt-tree-node-header';

    this.toggleBtn = document.createElement('button');
    this.toggleBtn.type = 'button';
    this.toggleBtn.className = 'world-nbt-tree-toggle';
    this.toggleBtn.addEventListener('click', () => {
      this.setCollapsed(!this.collapsed);
    });
    header.appendChild(this.toggleBtn);

    if (this.nameEditable) {
      this.nameInput = document.createElement('input');
      this.nameInput.type = 'text';
      this.nameInput.className = 'world-nbt-tree-key';
      this.nameInput.placeholder = 'name';
      this.nameInput.value = this.name;
      this.nameInput.addEventListener('input', () => {
        this.name = String(this.nameInput.value || '');
      });
      header.appendChild(this.nameInput);
    } else {
      this.nameInput = null;
    }

    this.typeSelect = createTypeSelect(this.type, { allowedTypes: ALL_TYPE_OPTIONS });
    this.typeSelect.addEventListener('change', () => {
      const nextType = Number(this.typeSelect.value) || NBT.END;
      if (nextType === this.type) return;
      this.type = nextType;
      this.value = defaultValueForType(nextType);
      this._render();
      if (this.onTypeChange) this.onTypeChange(this);
    });
    header.appendChild(this.typeSelect);

    this.actionsEl = document.createElement('div');
    this.actionsEl.className = 'world-nbt-tree-node-actions';
    header.appendChild(this.actionsEl);

    if (this.onRemove) {
      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'danger world-nbt-tree-remove-btn';
      removeBtn.textContent = 'Remove';
      removeBtn.addEventListener('click', () => {
        try { this.element.remove(); } catch (_e) { /* ignore */ }
        this.onRemove(this);
      });
      this.actionsEl.appendChild(removeBtn);
    }

    this.element.appendChild(header);
  }

  _buildBody() {
    this.body = document.createElement('div');
    this.body.className = 'world-nbt-tree-node-body';
    this.element.appendChild(this.body);
  }

  _isCollapsible() {
    return this.type !== NBT.END;
  }

  _syncCollapseUi() {
    const collapsible = this._isCollapsible();
    if (!collapsible) this.collapsed = false;

    if (this.toggleBtn) {
      this.toggleBtn.disabled = !collapsible;
      this.toggleBtn.textContent = this.collapsed ? unicodeList.dropdown_close : unicodeList.dropdown_open;
      this.toggleBtn.setAttribute('aria-hidden', collapsible ? 'false' : 'true');
      this.toggleBtn.setAttribute('aria-label', this.collapsed ? 'Expand tag' : 'Collapse tag');
    }

    if (this.body) {
      this.body.hidden = collapsible ? this.collapsed : false;
    }

    this.element.classList.toggle('is-collapsed', collapsible && this.collapsed);
  }

  setCollapsed(collapsed) {
    this.collapsed = !!collapsed && this._isCollapsible();
    this._syncCollapseUi();
  }

  _clearBody() {
    while (this.body.firstChild) this.body.removeChild(this.body.firstChild);
  }

  _render() {
    this._clearBody();

    if (this.type === NBT.END) {
      const note = document.createElement('span');
      note.className = 'world-nbt-tree-note';
      note.textContent = 'End tags hold no value.';
      this.body.appendChild(note);
      this._syncCollapseUi();
      return;
    }

    if (this.type === NBT.STRING) {
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'world-nbt-tree-value';
      input.value = this.value === null || this.value === undefined ? '' : String(this.value);
      input.addEventListener('input', () => { this.value = String(input.value); });
      this.body.appendChild(input);
      this._syncCollapseUi();
      return;
    }

    if (NUMERIC_TAGS.has(this.type)) {
      const input = document.createElement('input');
      input.type = 'text';
      input.inputMode = isFloatType(this.type) ? 'decimal' : 'numeric';
      input.className = 'world-nbt-tree-value';
      input.value = this.value === null || this.value === undefined ? '' : String(this.value);
      input.addEventListener('input', () => {
        const raw = String(input.value || '').trim();
        if (!raw) { this.value = 0; return; }
        const parsed = Number(raw);
        if (Number.isFinite(parsed)) {
          this.value = isFloatType(this.type) ? parsed : Math.trunc(parsed);
          input.classList.remove('invalid');
        } else {
          input.classList.add('invalid');
        }
      });
      this.body.appendChild(input);
      this._syncCollapseUi();
      return;
    }

    if (ARRAY_TAGS.has(this.type)) {
      const textarea = document.createElement('textarea');
      textarea.className = 'world-nbt-tree-value world-nbt-tree-array';
      textarea.spellcheck = false;
      textarea.placeholder = 'Comma or whitespace separated numbers';
      textarea.value = formatArrayValue(this.value);
      textarea.addEventListener('input', () => {
        try {
          this.value = parseArrayInput(textarea.value, true);
          textarea.classList.remove('invalid');
        } catch (_e) {
          textarea.classList.add('invalid');
        }
      });
      this.body.appendChild(textarea);
      this._syncCollapseUi();
      return;
    }

    if (this.type === NBT.COMPOUND) {
      this._renderCompound();
      this._syncCollapseUi();
      return;
    }

    if (this.type === NBT.LIST) {
      this._renderList();
      this._syncCollapseUi();
    }
  }

  _renderCompound() {
    if (!isObject(this.value)) this.value = {};

    const childrenWrap = document.createElement('div');
    childrenWrap.className = 'world-nbt-tree-children';
    this.body.appendChild(childrenWrap);

    this._compoundChildren = [];

    Object.keys(this.value).forEach((key) => {
      const childTag = this.value[key];
      const childType = isObject(childTag) ? Number(childTag.type) || NBT.END : NBT.END;
      const childValue = isObject(childTag) ? childTag.value : null;
      this._addCompoundChild(childrenWrap, key, childType, childValue);
    });

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'primary world-nbt-tree-add-btn';
    addBtn.textContent = 'Add Child Tag';
    addBtn.addEventListener('click', () => {
      const newKey = this._generateUniqueKey('newTag');
      this._addCompoundChild(childrenWrap, newKey, NBT.STRING, '');
    });
    this.body.appendChild(addBtn);
  }

  _generateUniqueKey(base) {
    let candidate = base;
    let counter = 1;
    const usedKeys = new Set((this._compoundChildren || []).map((child) => child.name));
    while (usedKeys.has(candidate)) {
      counter += 1;
      candidate = `${base}${counter}`;
    }
    return candidate;
  }

  _addCompoundChild(container, name, type, value) {
    const child = new TagNode({
      name,
      type,
      value,
      nameEditable: true,
      onRemove: (removed) => {
        this._compoundChildren = (this._compoundChildren || []).filter((entry) => entry !== removed);
      },
    });
    if (!this._compoundChildren) this._compoundChildren = [];
    this._compoundChildren.push(child);
    container.appendChild(child.element);
  }

  _renderList() {
    if (!isObject(this.value)) this.value = { list_type: NBT.END, items: [] };
    if (!Array.isArray(this.value.items)) this.value.items = [];

    const controls = document.createElement('div');
    controls.className = 'world-nbt-tree-list-controls';

    const listTypeLabel = document.createElement('span');
    listTypeLabel.className = 'world-nbt-tree-list-label';
    listTypeLabel.textContent = 'Items type';
    controls.appendChild(listTypeLabel);

    const listTypeSelect = createTypeSelect(Number(this.value.list_type) || NBT.END, {
      allowedTypes: ALL_TYPE_OPTIONS,
      includeEnd: true,
    });
    controls.appendChild(listTypeSelect);

    const itemsCountNote = document.createElement('span');
    itemsCountNote.className = 'world-nbt-tree-note';
    controls.appendChild(itemsCountNote);

    this.body.appendChild(controls);

    const itemsWrap = document.createElement('div');
    itemsWrap.className = 'world-nbt-tree-children world-nbt-tree-list-items';
    this.body.appendChild(itemsWrap);

    this._listItems = [];

    const updateItemsCount = () => {
      const count = this._listItems.length;
      itemsCountNote.textContent = `${count} item${count === 1 ? '' : 's'}`;
    };

    const buildItem = (rawItem, listType) => {
      const tagShaped = wrapItemAsTag(listType, rawItem);
      const node = new TagNode({
        name: '',
        type: listType,
        value: tagShaped.value,
        nameEditable: false,
        onRemove: (removed) => {
          this._listItems = this._listItems.filter((entry) => entry !== removed);
          updateItemsCount();
        },
      });
      // Lock the type to the list's items type — switching changes the
      // whole list so disable the per-item type editor.
      node.typeSelect.disabled = true;
      this._listItems.push(node);
      itemsWrap.appendChild(node.element);
    };

    const renderItems = () => {
      while (itemsWrap.firstChild) itemsWrap.removeChild(itemsWrap.firstChild);
      this._listItems = [];
      const listType = Number(this.value.list_type) || NBT.END;
      this.value.items.forEach((item) => buildItem(item, listType));
      updateItemsCount();
    };

    renderItems();

    const addItemBtn = document.createElement('button');
    addItemBtn.type = 'button';
    addItemBtn.className = 'primary world-nbt-tree-add-btn';
    addItemBtn.textContent = 'Add Item';
    addItemBtn.addEventListener('click', () => {
      const listType = Number(this.value.list_type) || NBT.END;
      if (listType === NBT.END) {
        // Cannot add to an End-typed list — pick a type first.
        return;
      }
      buildItem(defaultValueForType(listType), listType);
      updateItemsCount();
    });
    this.body.appendChild(addItemBtn);

    listTypeSelect.addEventListener('change', () => {
      const nextType = Number(listTypeSelect.value) || NBT.END;
      if (nextType === Number(this.value.list_type)) return;
      this.value.list_type = nextType;
      this.value.items = [];
      renderItems();
    });

    addItemBtn.disabled = (Number(this.value.list_type) || NBT.END) === NBT.END;
    listTypeSelect.addEventListener('change', () => {
      addItemBtn.disabled = (Number(listTypeSelect.value) || NBT.END) === NBT.END;
    });
  }

  // -------------------------------------------------------------------------
  // Serialisation
  // -------------------------------------------------------------------------

  toTag() {
    if (this.type === NBT.END) {
      return { type: NBT.END, value: null };
    }

    if (this.type === NBT.STRING) {
      return { type: NBT.STRING, value: this.value === null || this.value === undefined ? '' : String(this.value) };
    }

    if (NUMERIC_TAGS.has(this.type)) {
      const numeric = Number(this.value);
      const safe = Number.isFinite(numeric) ? numeric : 0;
      const final = isFloatType(this.type) ? safe : Math.trunc(safe);
      return { type: this.type, value: final };
    }

    if (ARRAY_TAGS.has(this.type)) {
      const arr = Array.isArray(this.value) ? this.value.slice() : [];
      return { type: this.type, value: arr.map((item) => Math.trunc(Number(item) || 0)) };
    }

    if (this.type === NBT.COMPOUND) {
      const value = {};
      const seen = new Set();
      (this._compoundChildren || []).forEach((child) => {
        const rawName = String(child.name || '').trim();
        if (!rawName) {
          throw new Error('Compound child tags must have a name.');
        }
        if (seen.has(rawName)) {
          throw new Error(`Compound has duplicate key "${rawName}".`);
        }
        seen.add(rawName);
        value[rawName] = child.toTag();
      });
      return { type: NBT.COMPOUND, value };
    }

    if (this.type === NBT.LIST) {
      const listType = Number((this.value && this.value.list_type) || NBT.END);
      const items = (this._listItems || []).map((itemNode) => unwrapItemFromTag(itemNode.toTag()));
      return {
        type: NBT.LIST,
        value: { list_type: listType, items },
      };
    }

    return { type: this.type, value: this.value };
  }
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

export const buildWorldNbtTreeEditor = (root) => {
  const safeRoot = isObject(root) ? cloneValue(root) : { type: NBT.COMPOUND, name: '', value: {} };
  const rootType = Number(safeRoot.type) || NBT.COMPOUND;
  const rootName = String(safeRoot.name || '');
  const rootValue = safeRoot.value;

  const wrapper = document.createElement('div');
  wrapper.className = 'world-nbt-tree-editor';

  const header = document.createElement('div');
  header.className = 'world-nbt-tree-root-header';

  const rootNameWrap = document.createElement('label');
  rootNameWrap.className = 'world-nbt-tree-root-name';
  const nameLabel = document.createElement('span');
  nameLabel.textContent = 'Root name';
  const rootNameInput = document.createElement('input');
  rootNameInput.type = 'text';
  rootNameInput.value = rootName;
  rootNameWrap.appendChild(nameLabel);
  rootNameWrap.appendChild(rootNameInput);
  header.appendChild(rootNameWrap);

  wrapper.appendChild(header);

  const rootNode = new TagNode({
    name: '',
    type: rootType === NBT.COMPOUND ? rootType : NBT.COMPOUND,
    value: isObject(rootValue) ? rootValue : {},
    nameEditable: false,
  });
  // Hide the root's type selector — changing the root type would invalidate
  // every value below, which the world editor's parser rejects anyway.
  rootNode.typeSelect.disabled = true;
  rootNode.element.classList.add('world-nbt-tree-root-node');

  wrapper.appendChild(rootNode.element);

  return {
    element: wrapper,
    getRoot: () => {
      const tag = rootNode.toTag();
      const rawName = String(rootNameInput.value || '');
      const finalRoot = { type: tag.type, name: rawName, value: tag.value };
      if (Number(finalRoot.type) !== NBT.COMPOUND) {
        throw new Error('The root tag must remain a compound (type 10).');
      }
      if (!isObject(finalRoot.value)) {
        throw new Error('The root value must be a compound payload.');
      }
      return finalRoot;
    },
  };
};

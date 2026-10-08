"""Element mapping and dynamic class instantiation for generic SVG element creation"""

import inkex

# Fallback mapping for cases where tag name doesn't match class name
TAG_TO_CLASS_MAPPING = {
    # Shape aliases
    "rect": "Rectangle",
    "text": "TextElement",
    "path": "PathElement",
    # Group elements
    "g": "Group",
    # Other common elements
    "use": "Use",
    "image": "Image",
    # Inkscape specific elements (require namespace)
    "inkscape:path-effect": "PathEffect",
}

# Module categories for placement logic
DEFS_MODULES = {
    "inkex.elements._filters",  # Contains gradients, filters, patterns, etc.
}

# Abstract element classes that should not be dynamically instantiated
ABSTRACT_ELEMENTS = {
    "BaseElement",
    "IBaseElement",
    "ShapeElement",
    "Gradient",
    "Element",
}

# SVG tags / class names that belong in <defs>
DEFS_TAGS = {
    "lineargradient",
    "radialgradient",
    "meshgradient",
    "pattern",
    "filter",
    "marker",
    "clippath",
    "mask",
    "symbol",
}


def get_element_class(tag_name: str):
    """
    Get inkex element class from tag name using capitalization convention + fallback mapping

    Args:
        tag_name: SVG tag name (e.g., 'linearGradient', 'rect', 'circle')

    Returns:
        Element class or None if not found
    """
    if not tag_name:
        return None

    # Exclude abstract element names
    if tag_name in ABSTRACT_ELEMENTS:
        return None

    # First try capitalizing first letter (inkex convention)
    capitalized_name = tag_name[0].upper() + tag_name[1:]
    if capitalized_name in ABSTRACT_ELEMENTS:
        return None

    # Try to get class from inkex by capitalized name
    if hasattr(inkex, capitalized_name):
        potential_class = getattr(inkex, capitalized_name)
        if getattr(potential_class, '__name__', '') in ABSTRACT_ELEMENTS:
            return None
        # Verify it's actually an element class
        if hasattr(potential_class, '__mro__') and issubclass(potential_class, inkex.BaseElement):
            return potential_class

    # Fallback to explicit mapping
    mapped_class_name = TAG_TO_CLASS_MAPPING.get(tag_name)
    if mapped_class_name and mapped_class_name not in ABSTRACT_ELEMENTS and hasattr(inkex, mapped_class_name):
        cls = getattr(inkex, mapped_class_name)
        if getattr(cls, '__name__', '') not in ABSTRACT_ELEMENTS:
            return cls

    return None


def should_place_in_defs(element_class) -> bool:
    """
    Determine if element should be placed in <defs> section based on its module,
    tag name, or class name

    Args:
        element_class: The inkex element class or instance

    Returns:
        True if should be placed in defs, False for main SVG
    """
    if element_class is None:
        return False

    # Check if a class type
    if isinstance(element_class, type):
        class_name = getattr(element_class, '__name__', '').lower()
        if class_name in DEFS_TAGS:
            return True

        if hasattr(element_class, 'tag_name') and isinstance(element_class.tag_name, str):
            clean_tag = element_class.tag_name.lower().split('}')[-1]
            if clean_tag in DEFS_TAGS:
                return True

        if hasattr(element_class, '__module__') and element_class.__module__ in DEFS_MODULES:
            return True

        return False

    # Check if string tag name
    if isinstance(element_class, str):
        clean_tag = element_class.lower().split('}')[-1]
        return clean_tag in DEFS_TAGS

    # Check if element instance
    if hasattr(element_class, 'tag_name') and isinstance(element_class.tag_name, str):
        clean_tag = element_class.tag_name.lower().split('}')[-1]
        if clean_tag in DEFS_TAGS:
            return True

    if hasattr(element_class, 'tag') and isinstance(element_class.tag, str):
        clean_tag = element_class.tag.lower().split('}')[-1]
        if clean_tag in DEFS_TAGS:
            return True

    return False


def ensure_defs_section(svg):
    """
    Ensure the SVG document has a defs section and return it

    Args:
        svg: SVG document object

    Returns:
        The defs element
    """
    defs = getattr(svg, "defs", None)
    if defs is None:
        defs = inkex.Defs()
        if hasattr(svg, "append"):
            svg.append(defs)
        elif hasattr(svg, "add"):
            svg.add(defs)
        try:
            svg.defs = defs
        except AttributeError:
            pass
    return defs


def get_unique_id(
    svg,
    tag_name: str,
    custom_id: str | None = None,
    reserved_ids: set | None = None,
) -> str:
    """
    Generate unique ID for element with collision detection and auto-increment

    Args:
        svg: SVG document
        tag_name: Tag name for prefix
        custom_id: Optional custom ID
        reserved_ids: Optional set of already reserved IDs to avoid collisions

    Returns:
        Unique ID string (auto-incremented if collision detected)
    """
    reserved = reserved_ids if reserved_ids is not None else set()

    if custom_id:
        # Check for collision and auto-increment if needed
        original_id = custom_id
        counter = 1

        while custom_id in reserved or svg.getElementById(custom_id) is not None:
            custom_id = f"{original_id}_{counter}"
            counter += 1

        reserved.add(custom_id)
        return custom_id

    # Use tag name as prefix, converting camelCase to lowercase
    prefix = tag_name[0].lower() + tag_name[1:] if tag_name else "element"
    generated = svg.get_unique_id(prefix=prefix)

    candidate = generated
    counter = 1
    while candidate in reserved or (candidate != generated and svg.getElementById(candidate) is not None):
        candidate = f"{generated}_{counter}"
        counter += 1

    reserved.add(candidate)
    return candidate
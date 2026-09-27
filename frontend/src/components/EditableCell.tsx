import { useState, useRef, useEffect } from 'react';

interface EditableCellProps {
  value: string;
  onChange?: (newValue: string) => void;
  className?: string;
}

export function EditableCell({ value, onChange, className = '' }: EditableCellProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isEditing]);

  const handleDoubleClick = () => {
    setIsEditing(true);
    setEditValue(value);
  };

  const handleBlur = () => {
    setIsEditing(false);
    if (editValue !== value) {
      onChange?.(editValue);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleBlur();
    } else if (e.key === 'Escape') {
      setEditValue(value);
      setIsEditing(false);
    }
  };

  if (isEditing) {
    return (
      <input
        ref={inputRef}
        type="text"
        value={editValue}
        onChange={(e) => setEditValue(e.target.value)}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        className={`editable-input ${className}`}
        style={{
          background: 'transparent',
          border: 'none',
          color: 'var(--text)',
          fontSize: 'inherit',
          fontFamily: 'inherit',
          width: '100%',
          padding: '0',
          outline: 'none',
        }}
      />
    );
  }

  return (
    <td
      className={className}
      onDoubleClick={handleDoubleClick}
      style={{ cursor: 'text' }}
    >
      {value}
    </td>
  );
}
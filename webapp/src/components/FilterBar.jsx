export function FilterBar({ filters, categories, onFilterChange }) {
  const statusOptions = [
    { value: null, label: 'Все' },
    { value: 'pending', label: 'Ожидает' },
    { value: 'in_progress', label: 'В работе' },
    { value: 'completed', label: 'Выполнено' },
    { value: 'cancelled', label: 'Отменено' }
  ]

  return (
    <div className="filter-bar">
      <div className="filter-group">
        <label htmlFor="status-filter">Статус:</label>
        <select
          id="status-filter"
          value={filters.status || ''}
          onChange={(e) => onFilterChange({ status: e.target.value || null })}
        >
          {statusOptions.map(option => (
            <option key={option.value || 'all'} value={option.value || ''}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="filter-group">
        <label htmlFor="category-filter">Категория:</label>
        <select
          id="category-filter"
          value={filters.category_id || ''}
          onChange={(e) => onFilterChange({ category_id: e.target.value ? parseInt(e.target.value) : null })}
        >
          <option value="">Все</option>
          {categories.map(category => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

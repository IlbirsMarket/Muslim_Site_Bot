// Каталог отделён от интерфейса: после подключения базы замените загрузку MenuRepository.
window.MUSLIM_MENU = {
  categories: [
    { id: 'pizza', name: 'Пиццы', note: 'Размеры 25, 30, 35 см' },
    { id: 'burgers', name: 'Бургеры' }, { id: 'shawarma', name: 'Шаурма' },
    { id: 'salads', name: 'Салаты' }, { id: 'soups', name: 'Супы' },
    { id: 'drinks', name: 'Напитки' }, { id: 'desserts', name: 'Десерты' }
  ],
  dishes: [
    { id: 'pepperoni', category: 'pizza', name: 'Пепперони', description: 'Халяль-колбаса, моцарелла, томатный соус', prices: [550, 650, 790], available: true, badge: 'Любимый выбор' },
    { id: 'margherita', category: 'pizza', name: 'Маргарита', description: 'Томаты, моцарелла, базилик', prices: [450, 550, 690], available: true },
    { id: 'bbq', category: 'pizza', name: 'Куриная BBQ', description: 'Курица, соус барбекю, красный лук', prices: [590, 690, 830], available: true },
    { id: 'cheese', category: 'pizza', name: 'Четыре сыра', description: 'Моцарелла, чеддер, пармезан, дор блю', prices: [620, 720, 860], available: false },
    { id: 'meat', category: 'pizza', name: 'Мясная', description: 'Говядина, курица, халяль-колбаса, перец', prices: [650, 750, 890], available: true },
    { id: 'vegetable', category: 'pizza', name: 'Овощная', description: 'Перец, грибы, маслины, томаты, моцарелла', prices: [480, 580, 720], available: true },
    { id: 'cola', category: 'drinks', name: 'Кола 0,5 л', description: 'Прохладительный напиток · 0,5 л', prices: [80], available: true }
  ],
  extras: [{ id: 'mozzarella', name: 'Сыр моцарелла', price: 80 }, { id: 'jalapeno', name: 'Халапеньо', price: 50 }, { id: 'garlic', name: 'Чесночный соус', price: 40 }]
};

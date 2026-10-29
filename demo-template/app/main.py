def calculate_total(items):
    return sum(item['price'] for item in items)


if __name__ == '__main__':
    print(calculate_total([{'price': 10}, {}]))

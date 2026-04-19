# cerebro

In-process SDK del Cerebro Shift AI — multi-agent system for enterprise decision-making.

## Instalación

```bash
pip install git+https://github.com/madebyjred-sudo/SHIFT-CEREBRO.git
```

## Uso

```python
from cerebro import Cerebro

c = Cerebro(tenant="shift")
response = c.run("¿Cuánto vendimos este mes?")
print(response.text)
print(response.agent_used)
```

## Instanciación con agentes reducidos

```python
c = Cerebro(tenant="shift", agents=["roberto", "patricia"])
print(c.available_agents)  # ['roberto', 'patricia']
```

## Versión

```python
import cerebro
print(cerebro.__version__)  # 0.1.0
```

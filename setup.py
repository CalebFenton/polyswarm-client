from setuptools import setup


def parse_requirements():
    with open('requirements.txt', 'r') as f:
        return f.read().splitlines()


setup(
    name='polyswarm-client',
    version='0.1',
    description='Client library to simplify interacting with a polyswarmd instance',
    author='PolySwarm Developers',
    author_email='info@polyswarm.io',
    url='https://github.com/polyswarm/polyswarm-client',
    license='MIT',
    install_requires=parse_requirements(),
    include_package_data=True,
    packages=['polyswarmclient', 'ambassador', 'arbiter', 'microengine', 'arbiter.verbatimdb', 'corpus'],
    package_dir={
        'polyswarmclient': 'src/polyswarmclient',
        'ambassador': 'src/ambassador',
        'arbiter': 'src/arbiter',
        'microengine': 'src/microengine',
        'corpus': 'src/corpus',
        'arbiter.verbatimdb': 'src/arbiter/verbatimdb',
    },
    entry_points={
        'console_scripts': [
            'ambassador=ambassador.__main__:main',
            'arbiter=arbiter.__main__:main',
            'microengine=microengine.__main__:main',
            'verbatimdbgen=arbiter.verbatimdb.__main__:main',
            'reporter=polyswarmclient.reporter:main',
        ],
    },
)
